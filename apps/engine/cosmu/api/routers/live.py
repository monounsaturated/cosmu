# intent: the live trading control-plane — arm/defund/launch + venue/jurisdiction reads; inputs: typed requests; outputs: live state; invariants: live stays off by default; arming needs confirm + keys + a passed gate + paper maturity + regime.

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from cosmu.adapters.exec.binance import resolve_mode
from cosmu.api._shared import _brain_reference_bars, _metric, _portfolio, settings, store
from cosmu.api.models import (
    ActivateRequest,
    ActivateResponse,
    DefundRequest,
    DefundResponse,
    EligibleStrategy,
    JurisdictionOption,
    JurisdictionsResponse,
    LaunchActivateRequest,
    LaunchActivateResponse,
    LiveCaps,
    LivePosition,
    LivePositionsResponse,
    LiveVenue,
    LiveVenuesResponse,
    RulesRequest,
    RulesResponse,
    SetJurisdictionRequest,
    VenueRule,
    VenueCatalogResponse,
    VenueFeeInfo,
    VenueFeeTierInfo,
    VenueInstrumentInfo,
)
from cosmu.knowledge.store import utcnow
from cosmu.spine.universe import venue_rows
from cosmu.spine.venue import SUPPORTED_JURISDICTIONS, default_catalog

router = APIRouter()


def _live_mode() -> str:
    """The mode GET /live/positions reports — the adapter's resolved mode (testnet/live) or sim if disabled."""
    mode = resolve_mode(settings)
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
    reference = _brain_reference_bars()
    seen: set[str] = set()
    out: list[EligibleStrategy] = []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        if not live_eligibility_verdict(store, r["id"], reference).eligible:
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


@router.post("/live/defund", response_model=DefundResponse)
def live_defund(request: DefundRequest) -> DefundResponse:
    pf = _portfolio()
    if request.scope == "strategy" and request.version_id:
        rows = store.rows("SELECT instrument_id FROM positions WHERE strategy_version_id = ?", (request.version_id,))
        store.rows("UPDATE positions SET qty = '0', updated_at = ? WHERE strategy_version_id = ?", (utcnow(), request.version_id))
        defunded = [request.version_id]
    else:
        rows = store.rows("SELECT DISTINCT strategy_version_id FROM positions WHERE CAST(qty AS REAL) != 0")
        store.rows("UPDATE positions SET qty = '0', updated_at = ?", (utcnow(),))
        defunded = [str(r["strategy_version_id"] or "pool") for r in rows]
    pf.mark_to_market({})
    store.append_event(actor="human", kind="live_defunded", ref_type="live_caps", ref_id="global", payload={"scope": request.scope, "defunded": defunded})
    return DefundResponse(ok=True, defunded=defunded)


@router.get("/live/positions", response_model=LivePositionsResponse)
def live_positions() -> LivePositionsResponse:
    # All reads share ONE connection (store.reading()); opening one per query is slow on remote Postgres
    # because each store.row/rows() call otherwise opens+closes a new network connection.
    with store.reading():
        pf = _portfolio()
        live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
        armed = bool(live_row and live_row["enabled"]) and resolve_mode(settings) != "disabled"
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


# Which venues have LIVE execution credentials wired. Only Binance has an execution adapter + keys today;
# the others are legal-but-unwired ("not connected") until their adapter ships. Secrets stay server-side —
# the UI only ever sees the boolean.
def _venue_connected(venue_id: str) -> bool:
    if venue_id == "binance":
        return bool(settings.binance_api_key and settings.binance_api_secret)
    return False


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
    in the order gauntlet (only when live is armed — the SIM/forward-test lane is never constrained)."""
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

    # HARD live-eligibility gate: paper maturity (>= PAPER_MIN_DAYS net-positive) AND regime.
    # `override_paper` waives ONLY the paper precondition (logged below), never the regime gate.
    from cosmu.master.live_eligibility import paper_clock_origin, live_eligibility_verdict

    reference = _brain_reference_bars()
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
    return LaunchActivateResponse(
        armed=True, version_id=request.version_id, venue_id=request.venue_id, symbol=request.symbol,
        budget=request.budget, caps=caps, eligible=eligible, paper_days=ft_days,
        readiness=readiness, overridden=verdict.overridden,  # type: ignore[arg-type]
    )
