# intent: the SINGLE order path for paper AND live — every intended order runs the master/risk.py gauntlet first
# (reject + audit on fail), then if (live toggle ON + adapter active + strategy gate-passed + caps available +
# not kill-switched) it submits via the ExecutionAdapter, else it paper-fills deterministically; inputs: intended
# orders + the live flags + adapter + store + portfolio + risk/venue catalog; outputs: persisted executions,
# emitted events, updated positions; invariants: NOTHING bypasses the gauntlet, live is off unless ALL conditions
# hold, fills are idempotent on client_order_id, and a rejected order is audited not silently dropped.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from cosmu.adapters.exec.binance import to_ccxt_symbol
from cosmu.config.settings import RiskSettings
from cosmu.core.interfaces import Order
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import PaperPortfolio
from cosmu.master.risk import OrderIntent, PortfolioRiskState, validate_order_full
from cosmu.spine.venue import VenueCatalog


@dataclass(frozen=True)
class IntendedOrder:
    """One order the orchestrator wants placed. `gate_passed` is the strategy's deterministic-gate verdict — a
    live submit is impossible without it. `client_order_id` is the idempotency key (stable across replays)."""

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
    venue: str  # "paper" | "testnet" | "live"
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
    portfolio: PaperPortfolio,
    risk: RiskSettings,
    catalog: VenueCatalog,
) -> list[OrderOutcome]:
    """Process every intended order through the one path. Returns an outcome per order; persists executions,
    positions, and audit events as a side effect. A real venue submit happens ONLY when ALL hold:
    live_enabled AND adapter.active AND intent.gate_passed AND caps available AND not kill_switch."""
    outcomes: list[OrderOutcome] = []
    run_id = _run_id(store)
    daily = portfolio.daily_loss()

    for intent in intents:
        venue = catalog.venue(intent.venue_id)
        instrument = catalog.instrument(intent.symbol, intent.venue_id)
        coid = intent.coid()
        existing = portfolio.position(instrument.id, "paper", strategy_version_id=intent.strategy_version_id)
        live_pos = portfolio.position(instrument.id, _live_venue(adapter), strategy_version_id=intent.strategy_version_id)
        held = live_pos or existing

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
        )
        state = PortfolioRiskState(
            equity=portfolio.equity(),
            cash=portfolio.equity(),  # spot, no leverage: deployable cash <= equity (conservative)
            open_notional=_open_notional(portfolio),
            strategy_open_notional=_open_notional(portfolio, strategy_version_id=intent.strategy_version_id),
            drawdown_pct=portfolio.drawdown(),
            daily_loss=daily.daily_loss,
            daily_loss_cap=daily.cap,
            last_trade_was_loss=held.last_was_loss if held else False,
            avg_entry_price=held.avg_price if held and held.qty != 0 else None,
            existing_qty=held.qty if held else Decimal("0"),
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
            outcomes.append(OrderOutcome(coid, intent.symbol, accepted=False, routed_live=False, venue="paper", issues=decision.issues))
            continue

        route_live = bool(live_enabled and not kill_switch and intent.gate_passed and getattr(adapter, "active", False))
        venue_label = _live_venue(adapter) if route_live else "paper"
        fee = order_intent.notional * (venue.taker_fee_bps / Decimal("10000"))

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

        # Record the fill (deterministic for paper; for live we book the intended fill and reconcile via
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
            price=intent.price,
            fee=fee,
            strategy_version_id=intent.strategy_version_id,
        )
        _write_execution(store, run_id, intent, instrument.id, venue.id, fee, is_paper=not route_live, coid=coid)
        outcomes.append(OrderOutcome(coid, intent.symbol, accepted=True, routed_live=route_live, venue=venue_label, issues=[]))

    return outcomes


def _live_venue(adapter) -> str:
    mode = getattr(adapter, "mode", "disabled")
    return mode if mode in ("testnet", "live") else "paper"


def _open_notional(portfolio: PaperPortfolio, *, strategy_version_id: str | None = None) -> Decimal:
    total = Decimal("0")
    for p in portfolio.positions():
        if strategy_version_id is not None and p.strategy_version_id != strategy_version_id:
            continue
        total += abs(p.qty) * p.avg_price
    return total


def _already_filled(store: Store, coid: str) -> bool:
    row = store.row("SELECT id FROM executions WHERE fill_log LIKE ? LIMIT 1", (f'%"client_order_id": "{coid}"%',))
    return row is not None


def _write_execution(store: Store, run_id: str, intent: IntendedOrder, instrument_id: str, venue_id: str, fee: Decimal, *, is_paper: bool, coid: str) -> None:
    payload = {
        "side": "buy" if intent.side > 0 else "sell",
        "symbol": intent.symbol,
        "qty": str(intent.qty),
        "price": str(intent.price),
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
            "price": str(intent.price),
            "fee": str(fee.quantize(Decimal("0.00000001"))),
            "slippage": "0.0005",
            "order_type": intent.order_type,
            "is_paper": int(is_paper),
            "ts": utcnow(),
            "fill_log": payload,
        },
    )
    store.append_event(actor="master", kind="execution_filled", ref_type="execution", ref_id=execution_id, payload=payload)
