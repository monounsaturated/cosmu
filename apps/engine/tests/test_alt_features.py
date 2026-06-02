# The keystone for leading-signal strategies: alt-data (funding_rate, …) joined point-in-time into the
# screen backtest. Without it, alt features read None and their conditions can never fire. These tests pin
# (1) the as-of join never looks ahead, and (2) a funding-gated spec trades ONLY when the join is supplied.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint
from cosmu.data.backtest import align_asof, run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)


def _d(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


def _bar(day: int) -> Bar:
    return Bar(ts=_d(day), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"))


def test_align_asof_is_point_in_time_no_lookahead():
    bars = [_bar(d) for d in (1, 2, 3, 4)]
    points = [
        AltDataPoint(ts=_d(1), available_at=_d(2), value=0.001),  # observed day1 but only KNOWN day2
        AltDataPoint(ts=_d(3), available_at=_d(3), value=0.005),
    ]
    aligned = align_asof(points, bars)
    assert _d(1).isoformat() not in aligned          # day1: nothing known yet — never the day-2-published value
    assert aligned[_d(2).isoformat()] == 0.001        # day2: first point now available
    assert aligned[_d(3).isoformat()] == 0.005        # day3: newer point
    assert aligned[_d(4).isoformat()] == 0.005        # day4: carries the last known value forward


def _funding_gated_spec() -> StrategySpec:
    return StrategySpec(
        name="funding-gated-test",
        rationale="momentum that only fires while funding is below a ceiling — needs the alt join to trade",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=7),
        entry=[
            Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="mom_lookback")), op="gt", threshold=ParamRef(param="mom_floor")),
            Condition(feature=FeatureRef(name="funding_rate"), op="lt", threshold=ParamRef(param="funding_ceiling")),
        ],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "mom_lookback": ParamSpace(kind="int", lo=5, hi=20),
            "mom_floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "funding_ceiling": ParamSpace(kind="float", lo=0.0, hi=1.0),
            "stop": ParamSpace(kind="float", lo=0.05, hi=0.2),
            "tp": ParamSpace(kind="float", lo=0.05, hi=0.3),
        },
    )


def test_funding_gate_trades_only_with_alt_join():
    spec = _funding_gated_spec()
    params = {"mom_lookback": 10, "mom_floor": -0.5, "funding_ceiling": 0.01, "stop": 0.1, "tp": 0.2}
    bars = edge_bearing_screen_market(n=200)["BTCUSDT"]
    market = {"BTCUSDT": bars}
    fee = Decimal("10")

    # Funding sits below the ceiling on every bar → the funding condition can pass when joined.
    alt = {"BTCUSDT": {"funding_rate": {b.ts.isoformat(): 0.0001 for b in bars}}}

    with_alt = run_strategy_backtest(spec, params, market, fee_bps=fee, alt_by_symbol=alt)
    without_alt = run_strategy_backtest(spec, params, market, fee_bps=fee)  # funding_rate → None

    assert without_alt.num_trades == 0, "alt feature must be unsatisfiable without the join (prior behaviour)"
    assert with_alt.num_trades > 0, "the point-in-time alt join must make the funding-gated strategy tradable"
