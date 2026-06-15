# The first-class ALT-DATA / EVENT strategy TYPE: an event spec validates, run_event_backtest on a tiny
# synthetic bars+events fixture returns a BacktestMetrics-shaped result whose trades were fired BY the events
# (point-in-time on available_at), and an existing indicator spec still validates unchanged. The event lane
# reuses data/backtest's engine, so the metrics are the SAME shape the gate already scores.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.event_backtest import run_event_backtest, run_event_backtest_detailed
from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar
from cosmu.master.scorer import BacktestMetrics
from cosmu.strategy.event_router import is_event_kind, route_backtest
from cosmu.strategy.event_spec import (
    EVENT_FIRED_FEATURE,
    EventEntrySignal,
    EventFilter,
    apply_cooldown,
    event_fired_series,
    event_matches,
)
from cosmu.strategy.spec import (
    Condition,
    EventSetup,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)
from cosmu.strategy.static_check import validate_spec

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _bars(n: int, *, jump_at: int | None = None) -> list[Bar]:
    """Daily bars, flat 100 then (optionally) a +15% step at `jump_at` so a long opened just before resolves on a
    take-profit. Volume is large so slippage/impact stay tiny."""
    one = Decimal("1000000")
    out: list[Bar] = []
    price = 100.0
    for i in range(n):
        if jump_at is not None and i >= jump_at:
            price = 115.0
        p = Decimal(str(round(price, 6)))
        out.append(Bar(ts=_T0 + timedelta(days=i), open=p, high=p, low=p, close=p, volume=one))
    return out


def _event(day: int, *, magnitude=0.8, direction=1, provider="cryptopanic", symbols=("BTCUSDT",)) -> MarketEvent:
    ts = _T0 + timedelta(days=day)
    return MarketEvent(
        provider=provider, source="feed", symbols=symbols, ts=ts, available_at=ts,
        title=f"breaker day {day}", magnitude=magnitude, direction=direction, event_type="hack",
    ).hydrated()


def _event_spec() -> StrategySpec:
    return StrategySpec(
        name="event-test",
        rationale="enter on a high-magnitude bullish cryptopanic breaker; exit on stop/take/time",
        strategy_kind="event",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=10),
        entry=[],  # pure event entry — the trigger is the MarketEvent match, no price/TA condition
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.2),
            "tp": ParamSpace(kind="float", lo=0.05, hi=0.3),
        },
        event=EventSetup(entry=EventEntrySignal(filter=EventFilter(source="cryptopanic", min_magnitude=0.6, direction=1))),
    )


# --------------------------------------------------------------------------- 1) the event spec validates


def test_event_spec_validates_and_is_event_kind():
    spec = _event_spec()
    assert validate_spec(spec) == []  # no magic numbers, known features (entry empty), valid horizon/universe
    assert spec.strategy_kind == "event"
    assert is_event_kind(spec) is True


# --------------------------------------------------------------------------- 2) PIT event→bar matching


def test_event_fired_series_joins_on_available_at_not_ts():
    bars = _bars(10)
    filt = EventFilter(source="cryptopanic", min_magnitude=0.6, direction=1)
    # event known on day 3 → fires on the day-3 bar (the first bar whose interval contains available_at)
    fired = event_fired_series(bars, [_event(3)], filt, symbol="BTCUSDT")
    assert list(fired) == [bars[3].ts.isoformat()]
    # a future-only event (available_at past every bar) NEVER fires — no look-ahead
    assert event_fired_series(bars, [_event(99)], filt, symbol="BTCUSDT") == {}
    # a sub-threshold magnitude / wrong side / wrong provider does not match
    assert not event_matches(_event(3, magnitude=0.2), filt)
    assert not event_matches(_event(3, direction=-1), filt)
    assert not event_matches(_event(3, provider="rss"), filt)


def test_cooldown_collapses_a_burst_to_one_firing():
    bars = _bars(10)
    filt = EventFilter(source="cryptopanic")
    fired = event_fired_series(bars, [_event(2), _event(3), _event(4)], EventFilter(source="cryptopanic"))
    assert len(fired) == 3
    cooled = apply_cooldown(bars, fired, cooldown_bars=5)
    assert list(cooled) == [bars[2].ts.isoformat()]  # day-2 kept, days 3-4 suppressed within the window
    assert apply_cooldown(bars, fired, cooldown_bars=0) == fired  # 0 => unchanged


# --------------------------------------------------------------------------- 3) event backtest -> BacktestMetrics


def test_run_event_backtest_returns_metrics_shape_with_event_driven_trades():
    # 120 flat bars, +15% jump on day 60: an entry fired by an event just before the jump resolves on take-profit.
    bars = _bars(120, jump_at=60)
    market = {"BTCUSDT": bars}
    events = {"BTCUSDT": [_event(58)]}  # known day 58 -> fires day-58 bar -> next-bar entry rides the jump
    spec = _event_spec()
    params = {"stop": 0.1, "tp": 0.1}

    metrics = run_event_backtest(spec, params, market, events, fee_bps=Decimal("10"))
    assert isinstance(metrics, BacktestMetrics)
    # the synthetic event-fired entry produced at least one resolved trade
    assert metrics.num_trades >= 1

    # an event spec with NO events backtests to zero trades — honest, never fabricated
    none = run_event_backtest(spec, params, market, {"BTCUSDT": []}, fee_bps=Decimal("10"))
    assert none.num_trades == 0

    # the detailed result carries the same BacktestResult contract (val/holdout streams + per-symbol counts)
    detailed = run_event_backtest_detailed(spec, params, market, events, fee_bps=Decimal("10"))
    assert isinstance(detailed.metrics, BacktestMetrics)
    assert "BTCUSDT" in detailed.symbol_trades


def test_router_dispatches_event_vs_indicator_to_same_metrics_shape():
    bars = _bars(120, jump_at=60)
    market = {"BTCUSDT": bars}
    events = {"BTCUSDT": [_event(58)]}
    ev = route_backtest(_event_spec(), {"stop": 0.1, "tp": 0.1}, market, fee_bps=Decimal("10"), events_by_symbol=events)
    assert isinstance(ev, BacktestMetrics)

    ind = _indicator_spec()
    assert is_event_kind(ind) is False
    out = route_backtest(ind, {"mom_floor": 0.0, "stop": 0.1, "tp": 0.1}, market, fee_bps=Decimal("10"))
    assert isinstance(out, BacktestMetrics)


# --------------------------------------------------------------------------- 4) existing indicator spec unchanged


def _indicator_spec() -> StrategySpec:
    return StrategySpec(
        name="indicator-test",
        rationale="plain momentum indicator strategy — must be byte-identical under the new optional fields",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=10),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=10), op="gt", threshold=ParamRef(param="mom_floor"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "mom_floor": ParamSpace(kind="float", lo=0.0, hi=0.1),
            "stop": ParamSpace(kind="float", lo=0.03, hi=0.2),
            "tp": ParamSpace(kind="float", lo=0.05, hi=0.3),
        },
    )


def test_existing_indicator_spec_validates_unchanged():
    spec = _indicator_spec()
    assert validate_spec(spec) == []
    # the new optional discriminator + payload default to the indicator lane with no event payload
    assert spec.strategy_kind == "indicator"
    assert spec.event is None
    # the synthetic event feature never leaks into an indicator spec's conditions
    assert all(c.feature.name != EVENT_FIRED_FEATURE for c in spec.entry)
