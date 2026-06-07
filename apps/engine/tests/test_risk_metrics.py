# Drawdown-aware metrics: Calmar (annualized return / maxDD) + Recovery Factor (total return / maxDD) — the
# return-per-unit-of-pain dimension the Sharpe is blind to. Pure, deterministic.

from __future__ import annotations

import math

from cosmu.master.risk_metrics import annualized_return, calmar_ratio, max_drawdown, recovery_factor


def test_max_drawdown_peak_to_trough():
    assert max_drawdown([]) == 0.0
    assert max_drawdown([0.1, 0.1, 0.1]) == 0.0  # monotone up → no drawdown
    # up to 1.2 then down to 0.6 → 50% drawdown
    assert math.isclose(max_drawdown([0.2, -0.5]), 0.5, abs_tol=1e-9)


def test_recovery_factor():
    assert recovery_factor(0.6, 0.3) == 2.0          # 60% return for 30% pain
    assert recovery_factor(0.5, 0.0) == math.inf     # no drawdown + up → inf
    assert recovery_factor(-0.1, 0.0) == 0.0         # no drawdown but down → 0
    assert recovery_factor(0.0, 0.2) == 0.0


def test_annualized_return_compounds():
    # +1% per day, 252 days → ~ (1.01)^252 - 1
    ann = annualized_return([0.01] * 252, 252)
    assert math.isclose(ann, 1.01 ** 252 - 1, rel_tol=1e-9)
    assert annualized_return([], 252) == 0.0
    assert annualized_return([-1.0], 252) == -1.0    # wiped out


def test_calmar_ratio_rewards_lower_drawdown():
    # two streams, same arithmetic mean, different drawdown path → lower-DD one has higher Calmar
    smooth = [0.01, 0.01, 0.01, 0.01]
    jagged = [0.05, -0.04, 0.05, -0.02]
    assert calmar_ratio(smooth, 252) > calmar_ratio(jagged, 252)
    assert calmar_ratio([0.01, 0.01], 252) == math.inf   # no drawdown, up → inf


def test_backtest_metrics_recovery_factor_property():
    from decimal import Decimal

    from cosmu.master.scorer import BacktestMetrics

    m = BacktestMetrics(oos_return=Decimal("0.6"), sharpe=Decimal("1"), sortino=Decimal("0"),
                        max_drawdown=Decimal("0.3"), win_rate=Decimal("0.5"), num_trades=10)
    assert m.recovery_factor == 2.0
