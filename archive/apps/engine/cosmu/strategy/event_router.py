# intent: the single dispatch seam that routes a StrategySpec to the correct backtest by its TYPE discriminator
# (strategy_kind), so the master can score indicator and event strategies through one call without knowing which
# engine to reach for; inputs: a StrategySpec + fitted params + market bars (+ events for the event lane);
# outputs: BacktestMetrics (gate-identical regardless of lane); invariants: 'indicator' (the default) routes to
# data/backtest.run_strategy_backtest BYTE-IDENTICALLY (every existing spec is unaffected), 'event'/'regime'
# routes to data/event_backtest.run_event_backtest, and the resulting metrics share one shape so the SAME
# downstream gate/scorer/cohort scores all lanes. No gate/scorer/cohort logic lives here — this only picks the
# entry-generation path.

from __future__ import annotations

from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.event_backtest import run_event_backtest
from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics
from cosmu.strategy.spec import StrategySpec

__all__ = ["route_backtest", "is_event_kind"]


def is_event_kind(spec: StrategySpec) -> bool:
    """True when the spec is an event/alt TYPE (entries from a MarketEvent), False for an indicator spec. Reads
    the optional discriminator defensively (getattr) so a spec built before the field existed reads 'indicator'."""
    return getattr(spec, "strategy_kind", "indicator") in ("event", "regime")


def route_backtest(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    events_by_symbol: dict[str, list[MarketEvent]] | None = None,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
) -> BacktestMetrics:
    """Dispatch by `strategy_kind`: an indicator spec runs the price/TA + alt-condition backtest exactly as
    before; an event/regime spec runs the event backtest (entries fire on a point-in-time `available_at`-joined
    MarketEvent). Both return the SAME BacktestMetrics shape, so the master can call this once and hand the
    result straight to the unchanged gate. `events_by_symbol` is required for the event lane (an event spec with
    no events backtests to zero trades — honest, never fabricated); it is ignored on the indicator lane."""
    if is_event_kind(spec):
        return run_event_backtest(
            spec,
            params,
            market,
            events_by_symbol or {},
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            impact_bps=impact_bps,
            size_multiplier=size_multiplier,
            alt_by_symbol=alt_by_symbol,
            size_series=size_series,
            include_holdout=include_holdout,
        )
    return run_strategy_backtest(
        spec,
        params,
        market,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        impact_bps=impact_bps,
        size_multiplier=size_multiplier,
        alt_by_symbol=alt_by_symbol,
        size_series=size_series,
        include_holdout=include_holdout,
    )
