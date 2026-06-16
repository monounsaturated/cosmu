# rank_consistency (master/scorer): the ADVISORY train→OOS rank-transfer diagnostic (RESEARCH_LESSONS §3 — "THE
# single most diagnostic check"). +1 = the in-sample ranking of a config grid transfers out-of-sample (stable);
# NEGATIVE = the best in-sample config is the worst out-of-sample (a curve-fit smell). It is surfaced on the gate
# verdict but NEVER changes pass/fail (the gate calibration is locked). These pin its discrimination + safe edges.

from __future__ import annotations

from cosmu.master.scorer import rank_consistency


def _const_halves(is_mean: float, oos_mean: float, n: int = 20) -> list[float]:
    """A per-config return series whose first half has mean `is_mean` and second half mean `oos_mean`."""
    return [is_mean] * n + [oos_mean] * n


def test_stable_grid_ranks_transfer_positive():
    # Each config keeps its relative performance across the chronological split → the IS ranking predicts OOS → +1.
    grid = [_const_halves(m, m) for m in (0.00, 0.01, 0.02, 0.03)]
    rho = rank_consistency(grid)
    assert rho is not None
    assert rho > 0.99  # a perfectly stable ranking


def test_overfit_grid_ranks_invert_negative():
    # The config that looked BEST in-sample is the WORST out-of-sample (IS mean ↑ with i, OOS mean ↓) → ~ -1.
    grid = [_const_halves(0.01 * i, -0.01 * i) for i in range(4)]
    rho = rank_consistency(grid)
    assert rho is not None
    assert rho < -0.99  # the curve-fit smell the diagnostic exists to surface


def test_no_relationship_is_near_zero():
    # IS ranks [1,2,3,4] vs OOS ranks [2,4,1,3] → Spearman sum-d²=10 → rho exactly 0: the in-sample ranking
    # carries no OOS information, and the diagnostic correctly reads ~0 (not a strong + or - signal).
    grid = [
        _const_halves(0.00, 0.01),
        _const_halves(0.01, 0.03),
        _const_halves(0.02, 0.00),
        _const_halves(0.03, 0.02),
    ]
    rho = rank_consistency(grid)
    assert rho is not None
    assert abs(rho) < 0.2


def test_fewer_than_two_configs_is_none():
    assert rank_consistency([]) is None
    assert rank_consistency([_const_halves(0.01, 0.01)]) is None


def test_too_short_series_is_none():
    assert rank_consistency([[0.1, 0.2], [0.3, 0.4]]) is None


def test_constant_performance_column_is_none():
    # All configs identical → in-sample performances are tied → ranks undefined → None (never a fake +1).
    grid = [_const_halves(0.01, 0.01) for _ in range(4)]
    assert rank_consistency(grid) is None
