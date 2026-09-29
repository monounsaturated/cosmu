# Funding annualization fix (#2): 8h funding settles ~3x/day, but the old accrual joined funding with
# `align_asof` (last-value-carried-forward) and accrued ONE print per bar — under-counting carry ~3x on daily
# bars and OVER-counting it (carry-forward) on sub-interval bars: 2-8x off. The fix sums EVERY settlement in
# each bar's interval (`sum_funding_per_bar`), reading the per-symbol settlement cadence FROM THE DATA, and the
# alt-join exposes it under FUNDING_ACCRUAL_KEY (kept separate from the funding LEVEL the conditions read).
# These tests pin the corrected figure and FAIL on the old align_asof-only behaviour.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.alt_join import build_alt_by_symbol
from cosmu.data.altdata import AltDataPoint, AltDataStore
from cosmu.data.backtest import (
    FUNDING_ACCRUAL_KEY,
    align_asof,
    run_strategy_backtest,
    sum_funding_per_bar,
)
from cosmu.data.market import Bar
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

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_RATE = 0.0001  # one 8h funding print


def _daily_bars(n: int) -> list[Bar]:
    one = Decimal("1000000")
    out: list[Bar] = []
    for i in range(n):
        p = Decimal(str(round(100.0 * (1.005**i), 6)))  # gentle rise so a long opens and holds
        out.append(Bar(ts=_T0 + timedelta(days=i), open=p, high=p, low=p, close=p, volume=one))
    return out


def _funding_points(days: int, rate: float = _RATE, *, step_hours: int = 8) -> list[AltDataPoint]:
    """Funding settlements every `step_hours` for `days` days; available_at == ts (published at settlement)."""
    n = int(days * 24 / step_hours)
    return [
        AltDataPoint(ts=_T0 + timedelta(hours=step_hours * k), available_at=_T0 + timedelta(hours=step_hours * k), value=rate)
        for k in range(n)
    ]


# --------------------------------------------------------------------------- the funding-only join (core)


def test_sum_funding_per_bar_sums_8h_prints_into_daily_bars():
    """A daily bar spans three 8h settlements → its accrual is 3x the per-print rate, NOT 1x (what align_asof,
    the level/condition join, returns by carrying the last print forward)."""
    bars = _daily_bars(10)
    pts = _funding_points(10)  # 3/day
    summed = sum_funding_per_bar(pts, bars)
    leveled = align_asof(pts, bars)
    mid = bars[5].ts.isoformat()
    assert round(summed[mid], 8) == round(3 * _RATE, 8), "daily bar must accrue all THREE 8h settlements"
    assert round(leveled[mid], 8) == round(_RATE, 8), "align_asof keeps the LEVEL (one print) — the old bug"
    assert summed[mid] != leveled[mid]


def test_sum_funding_per_bar_no_carry_forward_on_subinterval_bars():
    """1h bars vs 8h funding: only the ~3 settlement bars per day carry a value (each once); the other bars
    accrue nothing. The old carry-forward join repeated one 8h print across every 1h bar → ~8x over-count."""
    hbars = [Bar(ts=_T0 + timedelta(hours=h), open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1")) for h in range(48)]
    pts = _funding_points(2)  # 6 settlements over 48h
    summed = sum_funding_per_bar(pts, hbars)
    # exactly the settlement bars carry a value (not all 48), and the 2-day total is the true 6 prints' sum
    assert 0 < len(summed) <= 7, f"only settlement bars carry funding, got {len(summed)}"
    assert round(sum(summed.values()), 8) == round(6 * _RATE, 8)


# --------------------------------------------------------------------------- the alt-join wiring (fails on old)


def test_build_alt_by_symbol_exposes_summed_carry_separate_from_level(tmp_path):
    """The PIT alt-join must populate FUNDING_ACCRUAL_KEY with the per-bar SUMMED carry (3x on a daily bar) while
    keeping the funding_rate LEVEL (1x) for a funding-as-condition read. The OLD builder produced only the
    align_asof level and NO accrual key — so this assertion fails on the pre-fix behaviour."""
    store = AltDataStore(tmp_path / "alt")
    store.append("binance", "BTCUSDT", "funding_rate", _funding_points(10))  # funding_rate routes to binance, per-symbol
    bars = _daily_bars(10)
    spec = _funding_spec(direction=-1)

    alt = build_alt_by_symbol(store, spec, {"BTCUSDT": bars})
    assert alt is not None
    feats = alt["BTCUSDT"]
    assert FUNDING_ACCRUAL_KEY in feats, "the carry accrual series must be wired by the alt-join"
    mid = bars[5].ts.isoformat()
    assert round(feats[FUNDING_ACCRUAL_KEY][mid], 8) == round(3 * _RATE, 8), "accrual = summed 8h prints (3x)"
    assert round(feats["funding_rate"][mid], 8) == round(_RATE, 8), "level stays the point-in-time rate (1x)"


# --------------------------------------------------------------------------- end-to-end accrual magnitude


def _funding_spec(direction: int = 1) -> StrategySpec:
    return StrategySpec(
        name="funding-accrual-test",
        rationale="always-entering momentum; the held perp leg accrues funding so the magnitude is observable",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=120),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="lb")), op="gt", threshold=ParamRef(param="floor"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "lb": ParamSpace(kind="int", lo=2, hi=20),
            "floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "stop": ParamSpace(kind="float", lo=0.01, hi=0.9),
            "tp": ParamSpace(kind="float", lo=0.01, hi=0.9),
        },
        direction=direction,
        funding_feature="funding_rate",
    )


_PARAMS = {"lb": 5, "floor": -0.5, "stop": 0.9, "tp": 0.9}  # wide barriers → the time-stop holds the trade long


def test_accrual_series_scales_carry_pnl_and_level_fallback_matches():
    """A long perp pays funding: 3x the per-bar accrual costs strictly MORE than 1x (the magnitude bug was
    paying only 1/3). And a hand-built `funding_rate` LEVEL with no accrual key falls back to per-bar accrual,
    matching the 1x accrual-key run — so legacy sign-only fixtures keep working."""
    bars = _daily_bars(120)
    market = {"BTCUSDT": bars}
    keys = [b.ts.isoformat() for b in bars]
    fee = Decimal("10")

    alt_3x = {"BTCUSDT": {FUNDING_ACCRUAL_KEY: {k: 3 * _RATE for k in keys}}}
    alt_1x = {"BTCUSDT": {FUNDING_ACCRUAL_KEY: {k: _RATE for k in keys}}}
    alt_level = {"BTCUSDT": {"funding_rate": {k: _RATE for k in keys}}}  # no accrual key → fallback path

    long_3x = run_strategy_backtest(_funding_spec(direction=1), _PARAMS, market, fee_bps=fee, alt_by_symbol=alt_3x)
    long_1x = run_strategy_backtest(_funding_spec(direction=1), _PARAMS, market, fee_bps=fee, alt_by_symbol=alt_1x)
    long_level = run_strategy_backtest(_funding_spec(direction=1), _PARAMS, market, fee_bps=fee, alt_by_symbol=alt_level)

    assert long_1x.num_trades > 0
    assert long_3x.oos_return < long_1x.oos_return, "paying 3x funding must cost a long more than 1x"
    assert long_level.oos_return == long_1x.oos_return, "level fallback must accrue like a 1x accrual series"
