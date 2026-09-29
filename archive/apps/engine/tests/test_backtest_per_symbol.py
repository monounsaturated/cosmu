# The keystone for multi-symbol / multi-asset-class breadth: a backtest carries the SAME strategy's INDIVIDUAL
# result on EACH symbol (return/sharpe/max_drawdown/trades), not just the cross-sectional pooled metric. This is
# what "test the same strategy across crypto/stocks/indexes", out-of-asset generalization, deploy-where-confirmed,
# and the frontend per-symbol display all read. These tests pin the un-collapse plumbing (additive, default-empty).
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_population


def _series(step: str, n: int) -> list[Bar]:
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for i in range(n):
        o = price
        c = (price * Decimal(step)).quantize(Decimal("0.0001"))
        bars.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, c), low=min(o, c), close=c, volume=Decimal("1000000")))
        price = c
    return bars


def _chop(n: int) -> list[Bar]:
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for i in range(n):
        step = Decimal("1.02") if i % 2 == 0 else Decimal("0.98")
        o = price
        c = (price * step).quantize(Decimal("0.0001"))
        bars.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, c), low=min(o, c), close=c, volume=Decimal("1000000")))
        price = c
    return bars


def test_per_symbol_breakdown_uncollapses_the_cross_sectional_pool():
    market = {"RISE": _series("1.012", 240), "FALL": _series("0.990", 240), "CHOP": _chop(240)}
    spec = seed_population()[0]
    res = run_strategy_backtest_detailed(spec, fit_params(spec), market, fee_bps=Decimal("10"))

    # one entry per symbol that had enough bars, each carrying the full metric shape
    assert set(res.symbols_tested) == {"RISE", "FALL", "CHOP"}
    for m in res.per_symbol.values():
        assert set(m) == {"return", "sharpe", "max_drawdown", "trades"}
    # positive_symbols is EXACTLY the individually-profitable subset (the deploy-where-confirmed set) and never
    # exceeds the tested set — the consistency invariant a router will rely on.
    assert res.positive_symbols == [s for s, m in res.per_symbol.items() if m["return"] > 0]
    assert set(res.positive_symbols) <= set(res.symbols_tested)


def test_per_symbol_empty_when_no_symbol_has_enough_bars():
    spec = seed_population()[0]
    res = run_strategy_backtest_detailed(spec, fit_params(spec), {"X": _series("1.01", 40)}, fee_bps=Decimal("10"))
    # < 80 bars → the symbol is skipped; the breakdown (and the derived sets) are empty, never fabricated.
    assert res.per_symbol == {}
    assert res.symbols_tested == [] and res.positive_symbols == []


# ── Fix 2: the backtest equity curve uses the SAME T1 vol-target sizing as paper/live (realism parity) ──


def _vol_regime_market(n: int = 240) -> dict[str, list[Bar]]:
    """A trending series whose realized volatility SHIFTS partway through (calm → choppy), so vol-target sizing
    deploys a materially different notional than the static T0 fraction — the regime that makes the realism fix
    observable in the equity curve."""
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for i in range(n):
        # First half calm (+0.8%/bar), second half choppy with bigger swings — realized vol jumps mid-series.
        step = Decimal("1.008") if i < n // 2 else (Decimal("1.05") if i % 2 == 0 else Decimal("0.97"))
        o = price
        c = (price * step).quantize(Decimal("0.0001"))
        bars.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, c) * Decimal("1.001"),
                        low=min(o, c) * Decimal("0.999"), close=c, volume=Decimal("1000000")))
        price = c
    return {"VOLSHIFT": bars}


def test_backtest_curve_runs_vol_target_sizing_and_differs_from_t0():
    """T1 ON (the new default) sizes each bar with the vol-target envelope; T0 OFF reproduces the legacy static
    fraction. When realized vol diverges from the validation-window anchor the two curves MUST differ — proof the
    backtest now scores the SAME physics the paper/live executor trades, not a static fraction."""
    market = _vol_regime_market()
    spec = seed_population()[0]
    params = fit_params(spec)

    t1 = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), vol_target_sizing=True)
    t0 = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), vol_target_sizing=False)

    # Same trades/dates (sizing changes notional, NEVER which bars trade — entry/exit logic is untouched).
    assert t1.symbol_trades == t0.symbol_trades
    # T1 (default) is what run_strategy_backtest returns too — the production gate path.
    metrics_default = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10")).metrics
    assert metrics_default.oos_return == t1.metrics.oos_return
    # The vol-target envelope changed the realized return vs the static fraction (the realism delta).
    assert t1.metrics.oos_return != t0.metrics.oos_return


def test_vol_target_per_cell_uses_each_symbol_own_anchor_no_sibling_mix():
    """PER-COMBO: two symbols with DIFFERENT realized-vol profiles in the SAME backtest are each sized on THEIR
    OWN validation vol anchor — never a pooled/sibling value. Proof: running each symbol ALONE (its own anchor by
    construction) reproduces EXACTLY the per-symbol result it gets inside the pooled run. If a sibling's vol had
    leaked into a cell, the pooled-run cell would differ from its standalone run."""
    calm = _vol_regime_market(240)["VOLSHIFT"]              # one vol fingerprint
    steep = _series("1.012", 240)                          # a different (steeper, trending) fingerprint
    spec = seed_population()[0]
    params = fit_params(spec)

    pooled = run_strategy_backtest_detailed(
        spec, params, {"CALM": calm, "STEEP": steep}, fee_bps=Decimal("10"), vol_target_sizing=True
    )
    alone_calm = run_strategy_backtest_detailed(spec, params, {"CALM": calm}, fee_bps=Decimal("10"), vol_target_sizing=True)
    alone_steep = run_strategy_backtest_detailed(spec, params, {"STEEP": steep}, fee_bps=Decimal("10"), vol_target_sizing=True)

    assert set(pooled.per_symbol) == {"CALM", "STEEP"}
    # Each cell's pooled result == its standalone result → the cell was sized on ITS OWN anchor, with no sibling
    # vol pooled in (the per-combo BRUT invariant under T1 sizing).
    assert pooled.per_symbol["CALM"] == alone_calm.per_symbol["CALM"]
    assert pooled.per_symbol["STEEP"] == alone_steep.per_symbol["STEEP"]
