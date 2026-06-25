# intent: the live trading control-plane — arm/defund/launch + venue/jurisdiction reads; inputs: typed requests; outputs: live state; invariants: live stays off by default; arming needs confirm + keys + a passed gate + paper maturity + regime.

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from cosmu.adapters.exec.registry import live_mode
from cosmu.api._shared import _metric, _portfolio, _version_reference_bars, settings, store
from cosmu.api.models import (
    ActivateRequest,
    ActivateResponse,
    CancelOrderResponse,
    DefundRequest,
    DefundResponse,
    EligibleStrategy,
    JurisdictionOption,
    JurisdictionsResponse,
    LaunchActivateRequest,
    LaunchActivateResponse,
    LiquidateRequest,
    LiquidateResponse,
    LiveCaps,
    LiveOrder,
    LiveOrdersResponse,
    LivePosition,
    LivePositionsResponse,
    LiveVenue,
    LiveVenuesResponse,
    RulesRequest,
    RulesResponse,
    SetJurisdictionRequest,
    VenueCatalogResponse,
    VenueFeeInfo,
    VenueFeeTierInfo,
    VenueInstrumentInfo,
    VenueRule,
)
from cosmu.knowledge.store import utcnow
from cosmu.master.lifecycle import emit_lifecycle_event
from cosmu.spine.universe import venue_rows
from cosmu.spine.venue import SUPPORTED_JURISDICTIONS, default_catalog

router = APIRouter()


def _live_mode() -> str:
    """The mode GET /live/positions reports — the aggregate resolved mode across ALL wired venues (testnet/live)
    or sim if every venue is disabled. Aggregate (not Binance-only) so a Polymarket/Alpaca-armed state shows
    honestly instead of falsely reading 'sim'."""
    mode = live_mode(settings)
    return mode if mode in ("testnet", "live") else "sim"


def _live_caps_row() -> dict[str, float]:
    row = store.row("SELECT max_notional, max_daily_loss FROM live_caps WHERE id = 'global'")
    if row:
        return {
            "per_strategy_cap": float(settings.live.per_strategy_live_cap),
            "global_cap": float(row["max_notional"]),
            "max_daily_loss": float(row["max_daily_loss"]),
        }
    return {
        "per_strategy_cap": float(settings.live.per_strategy_live_cap),
        "global_cap": float(settings.live.global_live_cap),
        "max_daily_loss": float(settings.live.daily_loss_cap),
    }


def _eligible_strategies() -> list[EligibleStrategy]:
    """Strategies eligible to be armed: paper survivors that (a) passed the gates, (b) have >=
    PAPER_MIN_DAYS of net-positive FORWARD evidence, AND (c) whose PROVEN regime set includes the CURRENT
    market regime. All three are HARD preconditions — a 0-day-old, underwater, or out-of-regime strategy is NOT
    eligible. Capability ≠ edge: eligibility only gates WHAT CAN be armed; a human still makes the final launch
    click, and even then an order is real only with the toggle ON + keys + caps + no kill-switch. Never promotes."""
    from cosmu.master.live_eligibility import live_eligibility_verdict

    rows = store.rows(
        """
        SELECT sv.id, s.name FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        JOIN backtests b ON b.strategy_version_id = sv.id
        WHERE b.passed_gates = 1
        ORDER BY sv.created_at DESC LIMIT 20
        """
    )
    seen: set[str] = set()
    out: list[EligibleStrategy] = []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        # Regime reference resolved PER VERSION from its own asset class (equity→SPY, crypto→BTC) — never BTC
        # for an equity strategy.
        if not live_eligibility_verdict(store, r["id"], _version_reference_bars(r["id"])).eligible:
            continue  # blocked: not forward-proven (>= PAPER_MIN_DAYS net-positive) or out-of-regime
        out.append(EligibleStrategy(version_id=r["id"], name=r["name"]))
    return out


@router.post("/live/activate", response_model=ActivateResponse)
def live_activate(request: ActivateRequest) -> ActivateResponse:
    caps = LiveCaps(per_strategy_cap=request.per_strategy_cap, global_cap=request.global_cap, max_daily_loss=request.max_daily_loss)
    if not request.confirm:
        return ActivateResponse(armed=False, caps=caps, eligible=[], reason="activation requires confirm=true")
    store.rows(
        """
        INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global', 'pool', 'global', ?, ?)
        ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional, max_daily_loss = excluded.max_daily_loss
        """,
        (str(request.global_cap), str(request.max_daily_loss)),
    )
    eligible = _eligible_strategies()
    store.append_event(
        actor="human",
        kind="live_armed",
        ref_type="live_caps",
        ref_id="global",
        payload={"per_strategy_cap": request.per_strategy_cap, "global_cap": request.global_cap, "max_daily_loss": request.max_daily_loss, "eligible": [e.version_id for e in eligible]},
    )
    return ActivateResponse(armed=True, caps=caps, eligible=eligible)


def _liquidate_open_positions(version_id: str | None) -> int:
    """REAL exit for every OPEN position in scope: build a reduce_only IntendedOrder (opposite side, full held
    qty) per leg and route it through the ONE order path (master.execute_orders) with the leg's RESOLVED book +
    adapter, THEN let the caller zero/book the row. Returns how many legs an exit order was ACCEPTED for.

    Routing per leg follows the BOOK the leg lives on (the same split step_tracks uses), so a reduce_only never
    validates against the wrong book:
      - a 'sim'/'testnet'/paper position (no live adapter armed for its venue) sim-closes via the managed path
        (live_enabled=False, adapter=None) — degrades to today's behaviour when nothing is armed;
      - a 'live'/'testnet' position on an ARMED venue routes a real reduce-only order to that venue's exec
        adapter (live_enabled=True, adapter=<resolved>), which places reduce_only on the exchange.
    SAFE + IDEMPOTENT: a reduce_only is gauntlet-EXEMPT from caps/kill/regime (it only ever closes), the
    client_order_id is stamped per (version,instrument,book) so a re-call no-ops via execute_orders' fill guard,
    and a venue with no armed adapter falls to the sim/managed close (never a phantom order). Offline (no live
    mark) the order books at the position's own basis — a flat close, never a synthetic P&L."""
    from decimal import Decimal

    from cosmu.master.execution import IntendedOrder, execute_orders
    from cosmu.orchestrator.loop import PricingRouter, _instrument_venue

    pf = _portfolio()
    cat = default_catalog()
    open_positions = [
        p for p in pf.positions()
        if p.qty != 0 and (version_id is None or p.strategy_version_id == version_id)
    ]
    if not open_positions:
        return 0  # idempotent: nothing open → no order routed, the SQL-zero below is a no-op

    # The live adapters armed RIGHT NOW (toggle on + keys + mode). Empty unless the operator has armed live →
    # every leg sim-closes (today's behaviour). Resolving an adapter is side-effect-free + safe by construction.
    from cosmu.orchestrator.paper_step import _resolve_live_adapters

    live_adapters = _resolve_live_adapters(store)
    pricer = PricingRouter(cat, settings=settings)

    routed = 0
    for p in open_positions:
        venue_id = _instrument_venue(cat, p.instrument_id)
        if venue_id is None:
            continue  # unknown instrument → can't price/order it honestly; the SQL-zero still books it flat
        # A real (live/testnet) leg routes live ONLY if its venue is armed right now; otherwise (and for every
        # sim/paper leg) it sim-closes through the same managed path. This mirrors step_tracks' sim/live split.
        adapter = live_adapters.get(venue_id) if p.venue in ("live", "testnet") else None
        route_live = adapter is not None
        # Full-position market exit: opposite side, the entire held qty, reduce_only. Price = latest real mark,
        # falling back to the position's basis when offline (the gauntlet needs price > 0; a close at basis is a
        # flat exit, not a fabricated fill — live fills reconcile to the venue's true price out-of-band).
        mark = pricer.last_price(p.symbol, venue_id)
        price = mark if mark > 0 else p.avg_price
        if price <= 0:
            continue  # no honest price anywhere → skip the order; the SQL-zero books it flat
        side = -1 if p.qty > 0 else 1
        coid = f"liquidate-{p.strategy_version_id or 'pool'}-{p.instrument_id}-{p.venue}"
        intent = IntendedOrder(
            strategy_version_id=p.strategy_version_id or "pool",
            symbol=p.symbol,
            venue_id=venue_id,
            side=side,
            qty=abs(p.qty),
            price=price,
            stop_loss=None,
            take_profit=None,
            conviction=Decimal("0.5"),
            gate_passed=True,  # a reduce_only close is exempt from the entry gate; this only enables live routing
            client_order_id=coid,
            reduce_only=True,
        )
        outcomes = execute_orders(
            [intent],
            live_enabled=route_live,
            kill_switch=False,  # a STOP must never be trapped behind the kill-switch — closing IS the safety move
            adapter=adapter,
            store=store,
            portfolio=pf,
            risk=settings.risk,
            catalog=cat,
        )
        if outcomes and outcomes[0].accepted:
            routed += 1
    return routed


@router.post("/live/defund", response_model=DefundResponse)
def live_defund(request: DefundRequest) -> DefundResponse:
    """Defund a strategy (or the whole pool): FIRST route a real reduce_only liquidation for every open leg
    through the exec adapter (a real reduce-only order on an ARMED venue, a sim-close otherwise), THEN zero the
    book as the final bookkeeping. Before this, defund only zeroed the DB row and sold NOTHING — a live position
    could not actually be exited. Degrades to the old SQL-zero behaviour when no live adapter is armed."""
    pf = _portfolio()
    # Snapshot the defunded versions BEFORE routing — liquidation flattens the live legs it fully closes, so a
    # post-routing read would undercount the "all" scope. (For the strategy scope it is the one version.)
    if request.scope == "strategy" and request.version_id:
        defunded = [request.version_id]
    else:
        rows = store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE CAST(qty AS REAL) != 0")
        defunded = [str(r["strategy_version_id"] or "pool") for r in rows]
    # REAL EXIT FIRST: liquidate open legs on-venue (reduce_only) before the SQL-zero bookkeeping. Safe + a
    # no-op when nothing is open / nothing is armed (then this is byte-identical to the prior behaviour).
    liquidated = _liquidate_open_positions(request.version_id if request.scope == "strategy" else None)
    if request.scope == "strategy" and request.version_id:
        store.rows("UPDATE positions SET qty = '0', updated_at = ? WHERE strategy_version_id = ?", (utcnow(), request.version_id))
    else:
        store.rows("UPDATE positions SET qty = '0', updated_at = ?", (utcnow(),))
    pf.mark_to_market({})
    store.append_event(actor="human", kind="live_defunded", ref_type="live_caps", ref_id="global", payload={"scope": request.scope, "defunded": defunded, "liquidated": liquidated})
    # ADDITIVE lifecycle-trace audit mark (see master/lifecycle.py): each defunded version reached disarmed.
    for _vid in defunded:
        emit_lifecycle_event(store, _vid, "live_disarmed", {"scope": request.scope})
    return DefundResponse(ok=True, defunded=defunded, liquidated=liquidated)


@router.post("/live/liquidate", response_model=LiquidateResponse)
def live_liquidate(request: LiquidateRequest) -> LiquidateResponse:
    """Liquidate-all / per-strategy STOP — the real capital-safety exit. For every OPEN position in scope, route
    a reduce_only liquidation (opposite side, full qty) through the ONE order path with the leg's resolved live
    adapter: a real reduce-only order on an ARMED venue (so a LIVE position is genuinely exited on the exchange),
    a managed sim-close on the sim/unarmed path. The SQL-zero is the FINAL backstop after the order routes, so a
    residual (a partial venue fill / an instrument we can't price) is still booked flat. Idempotent: a second
    call with nothing open routes 0. NEVER opens exposure — reduce_only is exempt from the entry gate but can
    only close. Audited as `live_liquidated`."""
    target = request.version_id if request.scope == "strategy" else None
    # Snapshot the open versions in scope BEFORE routing — `_liquidate_open_positions` flattens the live legs it
    # fully closes, so reading after would undercount `closed`. (Distinct over the scope's currently-open rows.)
    if request.scope == "strategy" and request.version_id:
        opened = store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE CAST(qty AS REAL) != 0 AND strategy_version_id = ?", (request.version_id,))
        version_ids = [request.version_id] if opened else []
    else:
        opened = store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE CAST(qty AS REAL) != 0")
        version_ids = [str(r["strategy_version_id"] or "pool") for r in opened]

    routed = _liquidate_open_positions(target)
    # FINAL bookkeeping: zero any residual the venue exit didn't fully clear (partial fill / unpriced leg), so
    # the book reflects flat regardless. Mirrors defund's backstop; the reduce_only routing above did the selling.
    if request.scope == "strategy" and request.version_id:
        store.rows("UPDATE positions SET qty = '0', updated_at = ? WHERE strategy_version_id = ?", (utcnow(), request.version_id))
    else:
        store.rows("UPDATE positions SET qty = '0', updated_at = ?", (utcnow(),))
    _portfolio().mark_to_market({})
    store.append_event(
        actor="human", kind="live_liquidated", ref_type="live_caps", ref_id="global",
        payload={"scope": request.scope, "version_id": request.version_id, "routed": routed, "version_ids": version_ids},
    )
    for _vid in version_ids:
        emit_lifecycle_event(store, _vid, "live_disarmed", {"scope": request.scope, "via": "liquidate"})
    return LiquidateResponse(ok=True, scope=request.scope, routed=routed, closed=len(version_ids), version_ids=version_ids)


@router.get("/live/positions", response_model=LivePositionsResponse)
def live_positions() -> LivePositionsResponse:
    # All reads share ONE connection (store.reading()); opening one per query is slow on remote Postgres
    # because each store.row/rows() call otherwise opens+closes a new network connection.
    with store.reading():
        pf = _portfolio()
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
        armed = bool(live_row and live_row["enabled"]) and live_mode(settings) != "disabled"
        caps = LiveCaps(**_live_caps_row())
        daily = pf.daily_loss()
        positions = [
            LivePosition(
                instrument_id=p.instrument_id,
                symbol=p.symbol,
                qty=float(p.qty),
                avg_price=float(p.avg_price),
                unrealized_pnl=float(p.unrealized_pnl(p.avg_price)),  # mark==basis without a fresh tick; honest 0
                venue=p.venue,
            )
            for p in pf.positions()
        ]
    return LivePositionsResponse(armed=armed, mode=_live_mode(), daily_loss=float(daily.daily_loss), caps=caps, positions=positions)


def _coid_of(fill_log: object) -> str | None:
    """Pull the client_order_id out of an executions.fill_log (stored as a JSON string). The client_order_id
    is the engine's idempotency + cancel anchor; a row without one cannot be cancelled, so it is skipped."""
    if isinstance(fill_log, dict):
        coid = fill_log.get("client_order_id")
        return str(coid) if coid else None
    if isinstance(fill_log, str):
        try:
            coid = json.loads(fill_log).get("client_order_id")
        except (TypeError, ValueError, AttributeError):
            return None
        return str(coid) if coid else None
    return None


def _canceled_coids() -> set[str]:
    """The client_order_ids already cancelled live (an `order_canceled_live` event on the ledger). A cancel is
    audited as an event — there is no order-status column — so this is the single source for the 'canceled'
    badge on the orders panel."""
    out: set[str] = set()
    for r in store.rows("SELECT payload FROM events WHERE kind = 'order_canceled_live'"):
        coid = _coid_of(r["payload"])
        if coid:
            out.add(coid)
    return out


@router.get("/live/orders", response_model=LiveOrdersResponse)
def live_orders() -> LiveOrdersResponse:
    """The LIVE orders control-panel feed: every order that genuinely routed to a venue (executions.is_paper=0
    — testnet or live), NEVER the deterministic sim/paper lane. Each row carries venue/symbol/side/qty/price/
    status/order_id(client_order_id)/ts so the operator can see what is working and cancel it. Status is
    'working' until an `order_canceled_live` event is on the ledger for that id. With nothing routed live this
    returns an empty list (the honest 'nothing armed' state). Read-only — placing/cancelling is elsewhere."""
    # One connection for the batch (remote-Postgres latency — see live_positions). is_paper=0 is the ONLY
    # discriminator that admits a real-venue order; the sim/paper lane (is_paper=1) is structurally excluded.
    with store.reading():
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
        armed = bool(live_row and live_row["enabled"]) and live_mode(settings) != "disabled"
        canceled = _canceled_coids()
        rows = store.rows(
            "SELECT venue_id, side, qty, price, ts, fill_log, instrument_id FROM executions "
            "WHERE is_paper = 0 ORDER BY ts DESC LIMIT 200"
        )
    orders: list[LiveOrder] = []
    for r in rows:
        coid = _coid_of(r["fill_log"])
        if not coid:
            continue  # no client_order_id → not a cancellable order; never invent one
        log = json.loads(r["fill_log"]) if isinstance(r["fill_log"], str) else (r["fill_log"] or {})
        symbol = str(log.get("symbol") or r["instrument_id"] or "")
        side = "buy" if str(r["side"]).lower() == "buy" else "sell"
        orders.append(
            LiveOrder(
                order_id=coid,
                venue=str(r["venue_id"] or ""),
                symbol=symbol,
                side=side,  # type: ignore[arg-type]
                qty=_metric(r["qty"]),
                price=_metric(r["price"]),
                status="canceled" if coid in canceled else "working",
                ts=str(r["ts"]),
            )
        )
    return LiveOrdersResponse(armed=armed, mode=_live_mode(), orders=orders)


@router.post("/live/orders/{order_id}/cancel", response_model=CancelOrderResponse)
def cancel_live_order(order_id: str) -> CancelOrderResponse:
    """Cancel ONE live order at its venue. This is a real money-path control, so it is conservative:
      - the order_id (client_order_id) MUST exist on the LIVE ledger (executions.is_paper=0) — a sim/paper
        order is never cancellable (it never reached a venue), and an unknown id is an honest 404;
      - it resolves the order's OWN venue adapter via the exec registry and calls its `cancel`; a venue with no
        execution adapter (e.g. hyperliquid/ibkr are data-only today — Binance, Kraken, Alpaca and Polymarket
        all have exec adapters) returns an honest 'not implemented' instead of pretending to cancel;
      - the adapter is SAFE by construction (disabled with no keys → cancel raises), so this never fires a
        phantom request. The auth is the same x-api-key gate as every route. Audited as `order_canceled_live`.
    It NEVER places or modifies an order — only cancel. Idempotent: re-cancelling an already-cancelled id
    is reported as already canceled (no second venue call)."""
    from cosmu.adapters.exec.registry import adapter_for
    from cosmu.core.interfaces import OrderId

    with store.reading():
        row = store.row(
            "SELECT venue_id, fill_log FROM executions WHERE is_paper = 0 AND fill_log LIKE ? ORDER BY ts DESC LIMIT 1",
            (f'%"client_order_id": "{order_id}"%',),
        )
        already = order_id in _canceled_coids()
    if row is None:
        # Not on the live ledger → either unknown or a sim/paper-only id. Never cancel something off-venue.
        raise HTTPException(status_code=404, detail=f"no live order with id '{order_id}' (sim/paper orders are not cancellable)")
    venue_id = str(row["venue_id"] or "")
    if already:
        # Idempotent: the cancel is already audited; do not call the venue a second time.
        return CancelOrderResponse(canceled=True, order_id=order_id, venue=venue_id, reason="already canceled")

    adapter = adapter_for(venue_id, settings)
    if adapter is None:
        # Honest NotImplemented for a data-only venue (no exec adapter wired) — never fake a cancel.
        return CancelOrderResponse(canceled=False, order_id=order_id, venue=venue_id, reason=f"venue '{venue_id}' has no execution adapter — cancel not implemented")

    # Resolve the venue order id from the recorded fill_log when present (some venues cancel by their own id);
    # fall back to the client_order_id, which every adapter accepts as the cancel ref.
    log = json.loads(row["fill_log"]) if isinstance(row["fill_log"], str) else (row["fill_log"] or {})
    venue_order_id = log.get("venue_order_id")
    oid = OrderId(venue=venue_id, client_order_id=order_id, venue_order_id=str(venue_order_id) if venue_order_id else None)
    try:
        adapter.cancel(oid)
    except Exception as exc:  # noqa: BLE001 — a venue/adapter error must NEVER 500 the control plane nor leak a
        # secret-bearing message; surface only the type (e.g. disabled adapter / network) as an honest reason.
        return CancelOrderResponse(canceled=False, order_id=order_id, venue=venue_id, reason=f"venue rejected cancel ({type(exc).__name__})")

    store.append_event(
        actor="human", kind="order_canceled_live", ref_type="execution", ref_id=None,
        payload={"client_order_id": order_id, "venue": venue_id},
    )
    return CancelOrderResponse(canceled=True, order_id=order_id, venue=venue_id)


# Which venues have LIVE execution credentials wired (Binance, Alpaca, Polymarket have execution adapters).
# Delegates to the exec registry so key-presence has ONE source of truth shared with the live ignition; a
# venue with no adapter (or no keys) reports False — legal-but-unwired ("not connected"). Secrets stay
# server-side — the UI only ever sees the boolean.
def _venue_connected(venue_id: str) -> bool:
    from cosmu.adapters.exec.registry import keys_present

    return keys_present(venue_id, settings)


def _current_jurisdiction() -> str:
    """The operator's chosen jurisdiction: the latest audited `jurisdiction_set` event, else the
    LIVE_JURISDICTION env default — validated against the curated list so it's always a known code."""
    row = store.row("SELECT payload FROM events WHERE kind = 'jurisdiction_set' ORDER BY ts DESC LIMIT 1")
    if row:
        try:
            code = json.loads(row["payload"]).get("code")
            if code in SUPPORTED_JURISDICTIONS:
                return code
        except (TypeError, ValueError, KeyError):
            pass
    env = (settings.live_jurisdiction or "FR").upper()
    return env if env in SUPPORTED_JURISDICTIONS else "FR"


@router.get("/live/jurisdictions", response_model=JurisdictionsResponse)
def live_jurisdictions() -> JurisdictionsResponse:
    """The curated pick-list of operating jurisdictions + the current one. Each option lists the venues that
    are live-legal from there, so the UI can show what picking it unlocks."""
    catalog = default_catalog()
    options = [
        JurisdictionOption(code=code, label=label, legal_venue_ids=[v.id for v in catalog.live_legal_venues(code)])
        for code, label in SUPPORTED_JURISDICTIONS.items()
    ]
    return JurisdictionsResponse(current=_current_jurisdiction(), options=options)


@router.post("/live/jurisdiction", response_model=JurisdictionsResponse)
def set_live_jurisdiction(request: SetJurisdictionRequest) -> JurisdictionsResponse:
    code = request.code.upper()
    if code not in SUPPORTED_JURISDICTIONS:
        raise HTTPException(status_code=400, detail=f"unsupported jurisdiction: {request.code}")
    store.append_event(actor="operator", kind="jurisdiction_set", ref_type="config", ref_id="jurisdiction", payload={"code": code})
    return live_jurisdictions()


@router.get("/live/venues", response_model=LiveVenuesResponse)
def live_venues() -> LiveVenuesResponse:
    """The honest LIVE venue picture: the venues legal to trade from our jurisdiction, whether each is wired
    (connected) or not, whether it's ticked into the universe, and the real capital deployed at each now."""
    # All reads share ONE connection (store.reading()); opening one per query is slow on remote Postgres
    # because each store.row/rows() call otherwise opens+closes a new network connection.
    catalog = default_catalog()
    with store.reading():
        country = _current_jurisdiction()
        enabled_ids = {r["id"] for r in venue_rows(store) if r["enabled"]}
        deployed: dict[str, float] = {}
        for p in _portfolio().positions():  # real capital at risk per venue: |qty| * avg_price
            deployed[p.venue] = deployed.get(p.venue, 0.0) + abs(_metric(p.qty)) * _metric(p.avg_price)
        caps = LiveCaps(**_live_caps_row())
    venues = [
        LiveVenue(
            id=v.id,
            name=v.name,
            kind=v.kind,
            live_legal=True,  # this set is already filtered to legal-from-our-jurisdiction
            connected=_venue_connected(v.id),
            enabled=v.id in enabled_ids,
            deployed_usd=round(_metric(deployed.get(v.id, 0.0)), 2),
        )
        for v in catalog.live_legal_venues(country)
    ]
    total = round(sum(v.deployed_usd for v in venues), 2)
    return LiveVenuesResponse(jurisdiction=country, global_cap=caps.global_cap, total_deployed_usd=total, venues=venues)


def _venue_cap_rows() -> dict[str, float]:
    """The per-venue hard caps the operator set in the Rules modal (live_caps rows scope='venue')."""
    return {str(r["ref_id"]): float(r["max_notional"]) for r in store.rows("SELECT ref_id, max_notional FROM live_caps WHERE scope = 'venue'")}


@router.get("/live/rules", response_model=RulesResponse)
def live_rules() -> RulesResponse:
    """The live-trading Rules the operator edits: the hard global $ blocker + daily-loss + per-venue caps,
    with each legal venue's real deployed capital + headroom. The per-venue caps are enforced deterministically
    in the order gauntlet (only when live is armed — the SIM/paper lane is never constrained)."""
    catalog = default_catalog()
    with store.reading():
        country = _current_jurisdiction()
        caps = _live_caps_row()
        venue_caps = _venue_cap_rows()
        deployed: dict[str, float] = {}
        for p in _portfolio().positions():
            deployed[p.venue] = deployed.get(p.venue, 0.0) + abs(_metric(p.qty)) * _metric(p.avg_price)
    venues: list[VenueRule] = []
    for v in catalog.live_legal_venues(country):
        cap = venue_caps.get(v.id)
        dep = round(_metric(deployed.get(v.id, 0.0)), 2)
        venues.append(
            VenueRule(
                venue=v.id,
                name=v.name,
                max_notional=cap,
                deployed_usd=dep,
                available_usd=round(cap - dep, 2) if cap is not None else None,  # headroom under the cap, not exchange cash
            )
        )
    return RulesResponse(
        global_max_notional=caps["global_cap"],
        max_daily_loss=caps["max_daily_loss"],
        per_strategy_cap=caps["per_strategy_cap"],
        venues=venues,
    )


@router.post("/live/rules", response_model=RulesResponse)
def set_live_rules(request: RulesRequest) -> RulesResponse:
    """Set the live Rules: the global hard cap + daily-loss (the deterministic blocker) and per-venue caps.
    A per-venue cap of None CLEARS that venue's cap. Provided global fields update in place; omitted ones keep
    their current value. Audited. Setting caps NEVER arms live — the toggle/keys/gate interlocks still apply."""
    cur = _live_caps_row()
    gmax = request.global_max_notional if request.global_max_notional is not None else cur["global_cap"]
    gdl = request.max_daily_loss if request.max_daily_loss is not None else cur["max_daily_loss"]
    store.rows(
        """
        INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global', 'pool', 'global', ?, ?)
        ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional, max_daily_loss = excluded.max_daily_loss
        """,
        (str(gmax), str(gdl)),
    )
    for vr in request.venues:
        row_id = f"venue:{vr.venue}"
        if vr.max_notional is None:
            store.rows("DELETE FROM live_caps WHERE id = ?", (row_id,))
        else:
            store.rows(
                """
                INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES (?, 'venue', ?, ?, '0')
                ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional
                """,
                (row_id, vr.venue, str(vr.max_notional)),
            )
    store.append_event(
        actor="human",
        kind="live_rules_set",
        ref_type="live_caps",
        ref_id="global",
        payload={"global_max_notional": gmax, "max_daily_loss": gdl, "venues": [{"venue": vr.venue, "max_notional": vr.max_notional} for vr in request.venues]},
    )
    return live_rules()


@router.get("/live/venue-catalog", response_model=VenueCatalogResponse)
def live_venue_catalog() -> VenueCatalogResponse:
    """Read-only catalog for the launch-live modal: every venue with its real fee schedule and a
    `configured` boolean (True = API keys are present in server env for that venue; False = greyed-out
    in the UI, cannot arm). Keys are NEVER returned — only the boolean. This includes ALL venues in the
    catalog (not just the jurisdiction-legal subset) so the modal can show grey non-configured ones."""
    catalog = default_catalog()
    fee_venues = [
        VenueFeeInfo(
            id=v.id,
            name=v.name,
            kind=v.kind,
            maker_fee_bps=float(v.maker_fee_bps),
            taker_fee_bps=float(v.taker_fee_bps),
            min_notional=float(v.min_notional),
            slippage_bps=float(v.slippage_bps),
            impact_bps=float(v.impact_bps),
            region=v.region,
            legal_entity=v.legal_entity,
            fee_tiers=[
                VenueFeeTierInfo(
                    min_volume_30d_usd=float(t.min_volume_30d_usd),
                    maker_fee_bps=float(t.maker_fee_bps),
                    taker_fee_bps=float(t.taker_fee_bps),
                )
                for t in v.fee_tiers
            ],
            configured=_venue_connected(v.id),
            live_enabled=v.live_enabled,
        )
        for v in catalog.venues
    ]
    instruments = [
        VenueInstrumentInfo(
            id=i.id,
            venue_id=i.venue_id,
            symbol=i.symbol,
            asset_class=i.asset_class,
            min_notional=float(i.min_notional),
        )
        for i in catalog.instruments
    ]
    return VenueCatalogResponse(venues=fee_venues, instruments=instruments)


@router.post("/live/launch", response_model=LaunchActivateResponse)
def live_launch(request: LaunchActivateRequest) -> LaunchActivateResponse:
    """Strategy launch-live flow: arm one gate-passed strategy on a chosen venue + asset with a given budget.
    This is the ONLY path that launches a single strategy live — and the ONLY path that writes status='live'
    (on a confirmed, eligible launch). Paper maturity is now a HARD precondition: the strategy must have
    >= PAPER_MIN_DAYS of net-positive forward evidence AND be in a proven regime to arm. `override_paper`
    (default OFF) lets a human arm an UNPROVEN strategy anyway, recorded with a loud `live_override_launch` warning;
    it never waives the regime gate. The 5 execution interlocks still apply in full at execute time (toggle ON +
    keys present + gate passed + caps available + no kill-switch). `confirm` must be true (two-click safety)."""
    caps = LiveCaps(per_strategy_cap=request.per_strategy_cap, global_cap=request.global_cap, max_daily_loss=request.max_daily_loss)
    if not request.confirm:
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[], reason="confirm must be true to arm",
        )
    # Validate venue is configured (keys present). A non-configured venue CANNOT arm regardless
    # of the toggle — this is the server-side key-gate that backs the UI grey-out.
    if not _venue_connected(request.venue_id):
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[],
            reason=f"venue '{request.venue_id}' has no API keys configured — add them to the server env first",
        )

    # S×A×V ATTRIBUTION GUARD: the forward proof read just below (paper maturity, forward DSR, proven regimes)
    # was earned on the ONE (symbol, venue) the funder deployed this version on. Arming a DIFFERENT (symbol,
    # venue) would launch real money on evidence that belongs to another cell — the cardinal-sin on the money
    # path. Resolve the funded cell from the sim fill ledger (latest position for this version) and refuse a
    # mismatch. Fail-safe: no funded position yet → skip (the eligibility gate below still blocks an unproven arm).
    # (Until tracks are re-keyed per-triple, a version has exactly ONE funded cell; this keeps the arm honest now.)
    funded = store.row(
        "SELECT symbol, instrument_id FROM positions WHERE strategy_version_id = ? ORDER BY updated_at DESC LIMIT 1",
        (request.version_id,),
    )
    if funded and funded.get("symbol"):
        from cosmu.orchestrator.loop import _instrument_venue
        from cosmu.spine.venue import default_catalog

        funded_venue = _instrument_venue(default_catalog(), funded["instrument_id"]) or request.venue_id
        if funded["symbol"] != request.symbol or funded_venue != request.venue_id:
            return LaunchActivateResponse(
                armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
                budget=request.budget, caps=caps, eligible=[],
                reason=(f"forward proof was earned on {funded['symbol']}@{funded_venue}, not "
                        f"{request.symbol}@{request.venue_id} — arm the cell that was actually proven"),
            )

    # HARD live-eligibility gate: paper maturity (>= PAPER_MIN_DAYS net-positive) AND regime.
    # `override_paper` waives ONLY the paper precondition (logged below), never the regime gate.
    from cosmu.master.live_eligibility import live_eligibility_verdict, paper_clock_origin

    reference = _version_reference_bars(request.version_id)  # this version's own asset-class regime brain
    verdict = live_eligibility_verdict(store, request.version_id, reference, override=request.override_paper)
    ft_days = verdict.paper_age_days if paper_clock_origin(store, request.version_id) else None
    readiness = "proven" if verdict.forward_ready else "not yet proven"

    if not verdict.eligible:
        # Not forward-proven (and no override), underwater, or out-of-regime — refuse to arm. No status write.
        return LaunchActivateResponse(
            armed=False, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
            budget=request.budget, caps=caps, eligible=[], paper_days=ft_days,
            readiness=readiness, overridden=False, reason=verdict.reason,  # type: ignore[arg-type]
        )

    # Eligible (or human-overridden): upsert caps, then mark the strategy live. This UPDATE is the ONLY place
    # status='live' is written — a strategy becomes live only on a confirmed, eligible launch click.
    store.rows(
        """
        INSERT INTO live_caps(id, scope, ref_id, max_notional, max_daily_loss) VALUES ('global', 'pool', 'global', ?, ?)
        ON CONFLICT (id) DO UPDATE SET max_notional = excluded.max_notional, max_daily_loss = excluded.max_daily_loss
        """,
        (str(request.global_cap), str(request.max_daily_loss)),
    )
    store.rows("UPDATE strategy_versions SET status = 'live' WHERE id = ?", (request.version_id,))
    # FREEZE the EXACT config being armed → the live step (paper_step._frozen_config_ok) only opens REAL
    # positions on this frozen params_hash, never a silently re-fitted one. Idempotent (re-freezes in place);
    # the promotion sites froze it too, this guarantees the record exists at the moment of arming.
    from cosmu.master.promotion import freeze_promotion

    freeze_promotion(store, request.version_id)
    if verdict.overridden:
        # The explicit, logged warning for arming an unproven strategy (owner-pending escape hatch, default OFF).
        store.append_event(
            actor="human", kind="live_override_launch", ref_type="strategy_version", ref_id=request.version_id,
            payload={
                "reason": verdict.reason, "paper_age_days": verdict.paper_age_days,
                "net_return_pct": verdict.net_return_pct, "min_days": verdict.min_days,
                "venue_id": request.venue_id, "symbol": request.symbol,
            },
        )
    eligible = _eligible_strategies()
    store.append_event(
        actor="human", kind="live_launched", ref_type="strategy_version", ref_id=request.version_id,
        payload={
            "venue_id": request.venue_id, "symbol": request.symbol, "budget": request.budget,
            "per_strategy_cap": request.per_strategy_cap, "global_cap": request.global_cap,
            "max_daily_loss": request.max_daily_loss, "paper_days": ft_days,
            "readiness": readiness, "overridden": verdict.overridden,
        },
    )
    # ADDITIVE lifecycle-trace audit mark (see master/lifecycle.py): the version reached the armed stage.
    emit_lifecycle_event(store, request.version_id, "live_armed", {"venue_id": request.venue_id, "symbol": request.symbol, "overridden": verdict.overridden})
    return LaunchActivateResponse(
        armed=True, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
        budget=request.budget, caps=caps, eligible=eligible, paper_days=ft_days,
        readiness=readiness, overridden=verdict.overridden,  # type: ignore[arg-type]
    )
