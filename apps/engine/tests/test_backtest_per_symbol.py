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
