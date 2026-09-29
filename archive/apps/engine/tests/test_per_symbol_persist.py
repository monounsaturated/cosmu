# Guard test for per-symbol VISIBILITY persistence (the dropped granular data is now stored). Proves _backtest_row
# picks the highest-OOS symbol as best_symbol/best_pnl_pct and carries the full per_symbol JSON — WITHOUT touching
# the gate (best-of-N is display-only, never a funding signal). Pure: no backtest run. See the per_symbol
# migration + docs/epics/agentic-lane.md (per-symbol is also the granular surface the front will show).

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from cosmu.lab.finder import _backtest_row
from cosmu.master.scorer import BacktestMetrics


def _m() -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1"), sortino=Decimal("0"), max_drawdown=Decimal("0.1"),
        win_rate=Decimal("0.5"), num_trades=10, sharpe_per_obs=Decimal("0.05"), skew=Decimal("0"),
        kurtosis=Decimal("3"), n_obs=100, pbo=Decimal("0.1"), trials_counted=1,
        folds_positive_pct=Decimal("0.8"), holdout_deflated_sharpe=Decimal("0.05"),
    )


_VENUE = SimpleNamespace(id="binance", taker_fee_bps=Decimal("10"), slippage_bps=Decimal("5"), impact_bps=Decimal("50"))


def test_best_symbol_is_the_outlier_and_per_symbol_is_stored():
    # the exact handoff case: a single-symbol edge the pooled metric would bury
    per_symbol = {
        "LINKUSDT": {"return": 0.80, "sharpe": 2.1, "max_drawdown": 0.12, "trades": 8},
        "BTCUSDT": {"return": -0.05, "sharpe": -0.3, "max_drawdown": 0.20, "trades": 12},
        "ETHUSDT": {"return": 0.02, "sharpe": 0.1, "max_drawdown": 0.15, "trades": 9},
    }
    row = _backtest_row("v1", _m(), 0.9, True, True, _VENUE, per_symbol)
    assert row["best_symbol"] == "LINKUSDT"
    assert row["best_pnl_pct"] == "0.8"
    assert row["per_symbol"] == per_symbol  # full granular blob (JSON-serialized at insert)


def test_no_per_symbol_leaves_all_three_null():
    for ps in (None, {}):
        row = _backtest_row("v1", _m(), 0.9, True, True, _VENUE, ps)
        assert row["best_symbol"] is None
        assert row["best_pnl_pct"] is None
        assert row["per_symbol"] is None
