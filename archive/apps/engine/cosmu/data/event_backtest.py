# intent: backtest the first-class EVENT strategy type through the SAME engine indicator strategies use, so the
# gate sees an identical BacktestMetrics regardless of how the entry was generated; inputs: an event StrategySpec
# (strategy_kind='event'), real bars, and the per-symbol MarketEvent timelines; outputs: BacktestMetrics (and a
# detailed BacktestResult); invariants: the entry fires on a MarketEvent matching the spec's EventFilter joined
# POINT-IN-TIME on `available_at` (never `ts`), the exit reuses the spec's ExitRules unchanged, and the whole
# run delegates to data/backtest.run_strategy_backtest_detailed — no parallel backtest logic, no new cost model,
# no synthetic returns. The event firing is materialized as a synthetic point-in-time alt feature and injected
# through the existing alt-data join, so every downstream metric (split/holdout/PBO/DSR) is computed identically.

from __future__ import annotations

from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics
from cosmu.strategy.event_spec import EVENT_FIRED_FEATURE, apply_cooldown, event_fired_series
from cosmu.strategy.spec import (
    Condition,
    FeatureRef,
    ParamRef,
    ParamSpace,
    StrategySpec,
)

__all__ = ["run_event_backtest", "run_event_backtest_detailed", "build_event_indicator_spec"]

# The fitted-or-fixed threshold the synthetic event-fired condition reads. The series is 1.0 on firing bars and
# absent (None) elsewhere, so `gt EVENT_FIRED_THRESHOLD` fires iff a matching event became known in that bar's
# interval. Carried as a 0/1 fixed-point param so it travels through compile/score like any other ParamRef.
_EVENT_FIRED_PARAM = "__event_fired_threshold__"
_EVENT_FIRED_VALUE = 0.5


def build_event_indicator_spec(spec: StrategySpec) -> StrategySpec:
    """Project an event spec onto an INDICATOR-shaped spec the existing engine runs verbatim: prepend a synthetic
    entry condition that fires on the point-in-time `__event_fired__` feature (>0.5 ⇔ a matching event became
    known this bar), and register its fixed threshold in param_space. Everything else — exit rules, horizon,
    risk, direction, the rest of param_space — is carried through unchanged, so the backtest engine cannot tell
    an event entry from an indicator one and the gate scores them identically. The spec's own `entry` conditions
    (if any) are preserved and AND-ed after the event trigger, letting an event be additionally gated by a price
    filter. A non-event spec (strategy_kind != 'event') is returned unchanged."""
    if spec.strategy_kind != "event" or spec.event is None or spec.event.entry is None:
        return spec
    fired_condition = Condition(
        feature=FeatureRef(name=EVENT_FIRED_FEATURE),
        op="gt",
        threshold=ParamRef(param=_EVENT_FIRED_PARAM),
    )
    param_space = dict(spec.param_space)
    param_space[_EVENT_FIRED_PARAM] = ParamSpace(kind="choice", choices=[_EVENT_FIRED_VALUE])
    # Project to an indicator spec so the engine's entry path runs unchanged. strategy_kind flips to 'indicator'
    # ONLY on this internal projection — the caller's spec is untouched (model_copy is a deep-ish copy).
    return spec.model_copy(
        update={
            "strategy_kind": "indicator",
            "event": None,
            "entry": [fired_condition, *spec.entry],
            "param_space": param_space,
        }
    )


def _event_alt_by_symbol(
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    events_by_symbol: dict[str, list[MarketEvent]],
    base_alt: dict[str, dict[str, dict[str, float]]] | None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Materialize the point-in-time `__event_fired__` series per symbol and MERGE it onto any caller-supplied
    alt join (funding etc.), so an event strategy can ALSO read alt features in its remaining entry/exit
    conditions. The event firing joins on `available_at`; a symbol with no matching events simply carries no
    firing series (the feature reads None → the entry never fires → no trades, honestly)."""
    assert spec.event is not None and spec.event.entry is not None
    filt = spec.event.entry.filter
    cooldown = max(0, int(spec.event.entry.cooldown_bars))
    merged: dict[str, dict[str, dict[str, float]]] = {
        sym: dict(feats) for sym, feats in (base_alt or {}).items()
    }
    for symbol, bars in market.items():
        events = events_by_symbol.get(symbol, [])
        fired = apply_cooldown(bars, event_fired_series(bars, events, filt, symbol=symbol), cooldown)
        if fired:
            merged.setdefault(symbol, {})[EVENT_FIRED_FEATURE] = fired
    return merged


def run_event_backtest_detailed(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    events_by_symbol: dict[str, list[MarketEvent]],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
):
    """Backtest an event strategy and return the full BacktestResult. Projects the event spec onto an
    indicator-shaped spec (synthetic event-fired entry) and delegates to the SAME engine indicator strategies
    use, with the firing series injected through the alt-data join — so split/holdout/PBO/DSR/regime metrics are
    computed by identical code. The synthetic threshold is supplied automatically, so the caller's `params` need
    only cover the spec's own param_space."""
    indicator_spec = build_event_indicator_spec(spec)
    run_params = {**params, _EVENT_FIRED_PARAM: _EVENT_FIRED_VALUE}
    merged_alt = _event_alt_by_symbol(spec, market, events_by_symbol, alt_by_symbol)
    return run_strategy_backtest_detailed(
        indicator_spec,
        run_params,
        market,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        impact_bps=impact_bps,
        size_multiplier=size_multiplier,
        alt_by_symbol=merged_alt,
        size_series=size_series,
        include_holdout=include_holdout,
    )


def run_event_backtest(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    events_by_symbol: dict[str, list[MarketEvent]],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    size_multiplier: float = 1.0,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
    size_series: dict[str, float] | None = None,
    include_holdout: bool = True,
) -> BacktestMetrics:
    """Event-strategy backtest returning the scoreable BacktestMetrics — the gate-facing entry point. Thin
    wrapper over `run_event_backtest_detailed`; the entry fires on a point-in-time `available_at`-joined
    MarketEvent matching the spec's EventFilter, the exit reuses the spec's ExitRules, and the metrics are the
    SAME shape the indicator path produces (so the gate sees no difference)."""
    return run_event_backtest_detailed(
        spec,
        params,
        market,
        events_by_symbol,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        impact_bps=impact_bps,
        size_multiplier=size_multiplier,
        alt_by_symbol=alt_by_symbol,
        size_series=size_series,
        include_holdout=include_holdout,
    ).metrics
