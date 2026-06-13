# intent: the SINGLE order path for sim AND live — every intended order runs the master/risk.py gauntlet first
# (reject + audit on fail), then if (live toggle ON + adapter active + strategy gate-passed + caps available +
# not kill-switched) it submits via the ExecutionAdapter, else it sim-fills deterministically; inputs: intended
# orders + the live flags + adapter + store + portfolio + risk/venue catalog; outputs: persisted executions,
# emitted events, updated positions; invariants: NOTHING bypasses the gauntlet, live is off unless ALL conditions
# hold, fills are idempotent on client_order_id, and a rejected order is audited not silently dropped.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.exec.binance import to_ccxt_symbol
from cosmu.config.settings import RiskSettings
from cosmu.core.interfaces import Order
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.master.risk import OrderIntent, PortfolioRiskState, validate_order_full
from cosmu.spine.venue import VenueCatalog

# SIM fills cross the half-spread the ADVERSE way at this fraction — the same 5 bps base the gate-lane backtest
# charges (run_strategy_backtest's slippage_bps default), so paper P&L is never flattered relative to the
# screen that funded the track. (The backtest's participation-impact term needs bar volume, which the order path
# doesn't see — the base half-spread is the honest floor.) The executions row has always RECORDED slippage as
# 0.0005; this constant is what makes the fill price actually pay it. Live fills book the intended price and
# reconcile to the venue's true fill out-of-band (reconcile_fills).
_SIM_SLIPPAGE_FRACTION = Decimal("0.0005")


@dataclass(frozen=True)
class IntendedOrder:
    """One order the orchestrator wants placed. `gate_passed` is the strategy's deterministic-gate verdict — a
    live submit is impossible without it. `client_order_id` is the idempotency key (stable across replays).
    `reduce_only` marks an exit leg: it may only close (part of) an existing position — the gauntlet verifies
    it genuinely reduces and exempts it from the entry-shaped checks (brackets/caps/kill-switch)."""

    strategy_version_id: str
    symbol: str
    venue_id: str
    side: int  # +1 buy, -1 sell
    qty: Decimal
    price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    conviction: Decimal
    gate_passed: bool
    order_type: str = "market"
    client_order_id: str | None = None
    data_fresh: bool = True
    reduce_only: bool = False

    def coid(self) -> str:
        if self.client_order_id:
            return self.client_order_id
        raw = f"{self.strategy_version_id}:{self.symbol}:{self.side}:{self.qty}:{self.price}"
        return "cosmu-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


@dataclass(frozen=True)
class OrderOutcome:
    client_order_id: str
    symbol: str
    accepted: bool
    routed_live: bool
    venue: str  # "sim" | "testnet" | "live"
    issues: list[str] = field(default_factory=list)


def _run_id(store: Store) -> str:
    """A standing 'orchestrated' run row to satisfy executions.run_id FK without inventing a backtest run."""
    row = store.row("SELECT id FROM runs WHERE mode = 'orchestrated' LIMIT 1")
    if row:
        return str(row["id"])
    return store.insert(
        "runs",
        {"strategy_version_id": None, "mode": "orchestrated", "venue_id": None, "seed": 0, "started_at": utcnow(), "status": "running"},
    )


def execute_orders(
    intents: list[IntendedOrder],
    *,
    live_enabled: bool,
    kill_switch: bool,
    adapter,  # BinanceSpotExecutionAdapter (or any core.ExecutionAdapter); .active gates real submits
    store: Store,
    portfolio: Portfolio,
    risk: RiskSettings,
    catalog: VenueCatalog,
) -> list[OrderOutcome]:
    """Process every intended order through the one path. Returns an outcome per order; persists executions,
    positions, and audit events as a side effect. A real venue submit happens ONLY when ALL hold:
    live_enabled AND adapter.active AND intent.gate_passed AND caps available AND not kill_switch."""
    outcomes: list[OrderOutcome] = []
    run_id = _run_id(store)
    daily = portfolio.daily_loss()
    # Per-venue hard caps (Rules modal) apply ONLY when live is armed — so the SIM/forward-test lane (live off,
    # the default) is NEVER constrained by a live $-cap (which would silently distort the forward-test). Read
    # once per batch; enforced deterministically in the gauntlet via venue_max_notional.
    venue_caps = _venue_caps(store) if live_enabled else {}

    for intent in intents:
        venue = catalog.venue(intent.venue_id)
        instrument = catalog.instrument(intent.symbol, intent.venue_id)
        coid = intent.coid()
        existing = portfolio.position(instrument.id, "sim", strategy_version_id=intent.strategy_version_id)
        live_pos = portfolio.position(instrument.id, _live_venue(adapter), strategy_version_id=intent.strategy_version_id)
        held = live_pos or existing
        # A REDUCE-ONLY order must be validated against the book its FILL will land on — `live_pos or existing`
        # would let a live row vouch for a sim close (or vice versa): the gauntlet would pass against one book
        # while apply_fill's opening branch minted a phantom short on the other. The fill venue for a close is
        # exact here because closes are never regime-blocked (see below).
        if intent.reduce_only:
            _close_routes_live = bool(live_enabled and not kill_switch and intent.gate_passed and getattr(adapter, "active", False))
            state_held = live_pos if _close_routes_live else existing
        else:
            state_held = held

        order_intent = OrderIntent(
            symbol=intent.symbol,
            side="buy" if intent.side > 0 else "sell",
            qty=intent.qty,
            price=intent.price,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            conviction=intent.conviction,
            sizing_basis="equity_vol_conviction",
            data_fresh=intent.data_fresh,
            reduce_only=intent.reduce_only,
        )
        state = PortfolioRiskState(
            equity=portfolio.equity(),
            cash=portfolio.equity(),  # spot, no leverage: deployable cash <= equity (conservative)
            open_notional=_open_notional(portfolio),
            strategy_open_notional=_open_notional(portfolio, strategy_version_id=intent.strategy_version_id),
            drawdown_pct=portfolio.drawdown(),
            daily_loss=daily.daily_loss,
            daily_loss_cap=daily.cap,
            last_trade_was_loss=state_held.last_was_loss if state_held else False,
            avg_entry_price=state_held.avg_price if state_held and state_held.qty != 0 else None,
            existing_qty=state_held.qty if state_held else Decimal("0"),
            # Per-venue cap context — only populated when live is armed (else None → check skipped, SIM lane
            # unconstrained). venue_open_notional is what's already deployed on this order's venue.
            venue_open_notional=_open_notional(portfolio, venue=intent.venue_id) if live_enabled else Decimal("0"),
            venue_max_notional=venue_caps.get(intent.venue_id) if live_enabled else None,
        )
        decision = validate_order_full(order_intent, venue, instrument, risk, state)
        if not decision.accepted:
            store.append_event(
                actor="master",
                kind="order_rejected",
                ref_type="strategy_version",
                ref_id=intent.strategy_version_id,
                payload={"symbol": intent.symbol, "client_order_id": coid, "issues": decision.issues},
            )
            outcomes.append(OrderOutcome(coid, intent.symbol, accepted=False, routed_live=False, venue="sim", issues=decision.issues))
            continue

        # Regime eligibility gate: a live-routed ENTRY must be in a regime the strategy proved in. A
        # reduce-only close is exempt — blocking an exit because the regime moved would trap the very
        # position the regime change endangers. Failure → sim-fill with an audit event (never silently drops).
        regime_blocked = False
        if live_enabled and intent.gate_passed and getattr(adapter, "active", False) and not intent.reduce_only:
            try:
                from cosmu.ml.regime import current_regime, proven_regimes, regime_eligible

                regime_returns = _regime_returns(store, intent.strategy_version_id)
                if regime_returns is not None:
                    ref_bars = _reference_bars(adapter, intent.symbol)
                    if ref_bars:
                        now_regime = current_regime(ref_bars)
                        proven = proven_regimes(regime_returns)
                        if not regime_eligible(now_regime, proven):
                            regime_blocked = True
                            store.append_event(
                                actor="master",
                                kind="order_regime_blocked",
                                ref_type="strategy_version",
                                ref_id=intent.strategy_version_id,
                                payload={
                                    "symbol": intent.symbol,
                                    "current_regime": now_regime.label,
                                    "proven_regimes": sorted(proven),
                                    "client_order_id": coid,
                                },
                            )
            except Exception:  # noqa: BLE001 — regime check is advisory; failure falls through to sim
                pass

        route_live = bool(live_enabled and not kill_switch and intent.gate_passed and getattr(adapter, "active", False) and not regime_blocked)
        venue_label = _live_venue(adapter) if route_live else "sim"
        # SIM fills pay the half-spread the adverse way (buy fills above the mark, sell below) at the SAME
        # 5 bps base the gate-lane backtest charges — see _SIM_SLIPPAGE_FRACTION. Live books the intended
        # price and reconciles to the venue's actual fill out-of-band. Fees accrue on the true fill notional.
        fill_price = (
            intent.price
            if route_live
            else intent.price * (Decimal("1") + Decimal(intent.side) * _SIM_SLIPPAGE_FRACTION)
        )
        fee = _pit_fee_for_order(store, venue, intent.symbol, intent.qty, fill_price)

        if route_live:
            order = Order(
                instrument_id=to_ccxt_symbol(intent.symbol),
                side=intent.side,
                qty=intent.qty,
                order_type=intent.order_type,
                limit_price=intent.price if intent.order_type in ("limit", "maker") else None,
                client_order_id=coid,
                ts=datetime.now(tz=UTC),
            )
            order_id = adapter.submit(order)  # idempotent on client_order_id
            store.append_event(
                actor="master",
                kind="order_submitted_live",
                ref_type="strategy_version",
                ref_id=intent.strategy_version_id,
                payload={"symbol": intent.symbol, "client_order_id": order_id.client_order_id, "venue": venue_label, "venue_order_id": order_id.venue_order_id},
            )
            if intent.side > 0 and intent.take_profit is not None and intent.stop_loss is not None:
                _try_oco_bracket(adapter, intent, coid, store)

        # Record the fill (deterministic for sim; for live we book the intended fill and reconcile via
        # adapter.fills() out-of-band). Idempotent: a duplicate client_order_id is not re-applied.
        if _already_filled(store, coid):
            outcomes.append(OrderOutcome(coid, intent.symbol, accepted=True, routed_live=route_live, venue=venue_label, issues=[]))
            continue

        portfolio.apply_fill(
            instrument_id=instrument.id,
            symbol=intent.symbol,
            venue=venue_label,
            side=intent.side,
            qty=intent.qty,
            price=fill_price,
            fee=fee,
            strategy_version_id=intent.strategy_version_id,
        )
        _write_execution(store, run_id, intent, instrument.id, venue.id, fee, fill_price=fill_price, is_paper=not route_live, coid=coid)
        outcomes.append(OrderOutcome(coid, intent.symbol, accepted=True, routed_live=route_live, venue=venue_label, issues=[]))

    return outcomes


def _pit_fee_for_order(store: Store, venue, symbol: str, qty: Decimal, price: Decimal) -> Decimal:
    """Compute the taker fee for an order using the PIT fee schedule from the alt_data store.

    Falls back to the static catalog taker fee when no PIT snapshot exists (offline / pre-first-ingest).
    This is the single chokepoint that eliminates hardcoded fees in the order path.
    """
    from cosmu.data.altdata import read_pit_fee

    now = datetime.now(tz=UTC)
    taker_bps = read_pit_fee(store, venue.id, symbol, "venue_fees_taker", now)
    if taker_bps is not None:
        fee_fraction = Decimal(str(taker_bps)) / Decimal("10000")
    else:
        fee_fraction = venue.taker_fee_bps / Decimal("10000")
    notional = qty * price
    return notional * fee_fraction


def _live_venue(adapter) -> str:
    mode = getattr(adapter, "mode", "disabled")
    return mode if mode in ("testnet", "live") else "sim"


def _open_notional(portfolio: Portfolio, *, strategy_version_id: str | None = None, venue: str | None = None) -> Decimal:
    total = Decimal("0")
    for p in portfolio.positions():
        if strategy_version_id is not None and p.strategy_version_id != strategy_version_id:
            continue
        if venue is not None and p.venue != venue:
            continue
        total += abs(p.qty) * p.avg_price
    return total


def _venue_caps(store: Store) -> dict[str, Decimal]:
    """The per-venue hard caps the Rules modal persists (live_caps rows scope='venue', ref_id=venue). Read once
    per execution batch. Malformed rows are skipped (never crash the money path)."""
    caps: dict[str, Decimal] = {}
    for r in store.rows("SELECT ref_id, max_notional FROM live_caps WHERE scope = 'venue'"):
        try:
            caps[str(r["ref_id"])] = Decimal(str(r["max_notional"]))
        except Exception:  # noqa: BLE001 — a malformed cap row must never break execution.
            continue
    return caps


def _already_filled(store: Store, coid: str) -> bool:
    row = store.row("SELECT id FROM executions WHERE fill_log LIKE ? LIMIT 1", (f'%"client_order_id": "{coid}"%',))
    return row is not None


def _try_oco_bracket(adapter, intent: IntendedOrder, coid: str, store: Store) -> None:
    """Best-effort OCO bracket after a live BUY. Failure is logged, never fails the parent."""
    if not hasattr(adapter, "place_oco_bracket"):
        return
    result = adapter.place_oco_bracket(
        intent.symbol, intent.qty, intent.take_profit, intent.stop_loss, client_order_id_prefix=coid
    )
    kind = "oco_bracket_placed" if result is not None else "oco_bracket_failed"
    store.append_event(
        actor="master",
        kind=kind,
        ref_type="strategy_version",
        ref_id=intent.strategy_version_id,
        payload={"symbol": intent.symbol, "client_order_id": coid, "take_profit": str(intent.take_profit), "stop_loss": str(intent.stop_loss)},
    )


def _write_execution(store: Store, run_id: str, intent: IntendedOrder, instrument_id: str, venue_id: str, fee: Decimal, *, fill_price: Decimal, is_paper: bool, coid: str) -> None:
    payload = {
        "side": "buy" if intent.side > 0 else "sell",
        "symbol": intent.symbol,
        "qty": str(intent.qty),
        "price": str(fill_price),
        "client_order_id": coid,
        "slippage_model": "deterministic_bps",
        "commission": str(fee.quantize(Decimal("0.00000001"))),
        "is_paper": is_paper,
    }
    execution_id = store.insert(
        "executions",
        {
            "run_id": run_id,
            "strategy_version_id": intent.strategy_version_id,
            "instrument_id": instrument_id,
            "venue_id": venue_id,
            "side": "buy" if intent.side > 0 else "sell",
            "qty": str(intent.qty),
            "price": str(fill_price),
            "fee": str(fee.quantize(Decimal("0.00000001"))),
            # Paper fills genuinely PAY this fraction (see _SIM_SLIPPAGE_FRACTION — it is in fill_price);
            # a live fill's true slippage is only known at reconciliation, so it is recorded as 0 here.
            "slippage": str(_SIM_SLIPPAGE_FRACTION) if is_paper else "0",
            "order_type": intent.order_type,
            "is_paper": int(is_paper),
            "ts": utcnow(),
            "fill_log": payload,
        },
    )
    store.append_event(actor="master", kind="execution_filled", ref_type="execution", ref_id=execution_id, payload=payload)


def _regime_returns(store: Store, strategy_version_id: str) -> dict[str, float] | None:
    """Read the regime-tagged returns from the strategy's backtest. Returns None if no backtest exists."""
    row = store.row(
        "SELECT regime_label FROM backtests WHERE strategy_version_id = ? AND passed_gates = 1 ORDER BY id DESC LIMIT 1",
        (strategy_version_id,),
    )
    if not row or not row.get("regime_label"):
        return None
    import json
    raw = row["regime_label"]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {k: float(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return {str(raw): 1.0}


def _reference_bars(adapter, symbol: str) -> list[float]:
    """Get recent close prices from the adapter for regime classification. Best-effort."""
    if not hasattr(adapter, "reference_bars"):
        return []
    try:
        bars = adapter.reference_bars(symbol, limit=60)
        return [float(b.close) if hasattr(b, "close") else float(b) for b in bars]
    except Exception:  # noqa: BLE001
        return []


def reconcile_fills(
    adapter,
    store: Store,
    portfolio: Portfolio,
    *,
    since: datetime | None = None,
    fee_drift_alert_bps: float = 2.0,
) -> list[dict[str, str]]:
    """Fetch actual fills from the venue, compare with intended executions, update records, and log slippage.

    Extended in P0.4: also reconciles PREDICTED fee (from the PIT snapshot used at order time) vs the REALIZED
    fee (from the actual fill).  Drift > `fee_drift_alert_bps` is logged as a ``fee_model_drift`` event — the
    Slack-alert seam.  This feeds realized fees into per-strategy ROI and `cost_ratio` accounting.

    Called out-of-band after live orders (e.g. during the master tick's mark-to-market phase).
    """
    if not getattr(adapter, "active", False):
        return []
    lookback = since or (datetime.now(tz=UTC) - timedelta(hours=24))
    actual_fills = adapter.fills(lookback)
    events: list[dict[str, str]] = []

    for fill in actual_fills:
        coid = fill.order_id.client_order_id
        if not coid:
            continue
        exec_row = store.row(
            "SELECT id, price, qty, fee, strategy_version_id, instrument_id, venue_id FROM executions WHERE fill_log LIKE ? LIMIT 1",
            (f'%"client_order_id": "{coid}"%',),
        )
        if exec_row is None:
            continue
        intended_price = Decimal(str(exec_row["price"]))
        actual_price = fill.price
        slippage = actual_price - intended_price
        slippage_bps = (slippage / intended_price * Decimal("10000")) if intended_price else Decimal("0")

        # --- fee drift reconciliation (P0.4) ---
        predicted_fee = Decimal(str(exec_row["fee"])) if exec_row.get("fee") else Decimal("0")
        actual_fee = fill.fee
        # bps drift: (actual_fee - predicted_fee) / notional × 10000
        notional = actual_price * Decimal(str(exec_row["qty"])) if exec_row.get("qty") else actual_price
        fee_drift_bps = (
            (actual_fee - predicted_fee) / notional * Decimal("10000")
            if notional != Decimal("0") else Decimal("0")
        )

        store.rows(
            "UPDATE executions SET price = ?, fee = ? WHERE id = ?",
            (str(actual_price), str(actual_fee), exec_row["id"]),
        )

        event_payload: dict[str, str] = {
            "client_order_id": coid,
            "intended_price": str(intended_price),
            "actual_price": str(actual_price),
            "slippage": str(slippage),
            "slippage_bps": str(slippage_bps.quantize(Decimal("0.01"))),
            "actual_fee": str(actual_fee),
            "predicted_fee": str(predicted_fee),
            "fee_drift_bps": str(fee_drift_bps.quantize(Decimal("0.01"))),
        }
        store.append_event(
            actor="master",
            kind="fill_reconciled",
            ref_type="execution",
            ref_id=str(exec_row["id"]),
            payload=event_payload,
        )

        # Slack-alert seam: log a dedicated event when fee model drift exceeds the threshold.
        # The Slack webhook consumer (P1.3) reads ``fee_model_drift`` events and fires the alert.
        if abs(float(fee_drift_bps)) > fee_drift_alert_bps:
            store.append_event(
                actor="master",
                kind="fee_model_drift",
                ref_type="execution",
                ref_id=str(exec_row["id"]),
                payload={
                    "client_order_id": coid,
                    "fee_drift_bps": str(fee_drift_bps.quantize(Decimal("0.01"))),
                    "predicted_fee": str(predicted_fee),
                    "actual_fee": str(actual_fee),
                    "threshold_bps": str(fee_drift_alert_bps),
                    "strategy_version_id": str(exec_row.get("strategy_version_id") or ""),
                },
            )

        events.append(event_payload)

    return events
