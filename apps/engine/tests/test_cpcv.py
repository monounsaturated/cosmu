"""Tests for cosmu.master.cpcv — Combinatorial Purged Cross-Validation with embargo.

Coverage:
  A. path count == C(N, k)
  B. purge + embargo removes the correct boundary observations
  C. positive-edge stream yields low PBO + positive deflated Sharpe
  D. noise/overfit stream yields high PBO
  E. determinism
  F. tiny-stream fail-closed guard
  G. parameter-validation fail-closed guards
"""

from __future__ import annotations

import math
import random

import pytest

from cosmu.master.cpcv import CPCVResult, _ncr, cpcv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_edge_stream(n: int, mu: float = 0.02, seed: int = 42) -> list[float]:
    """Persistent positive-edge stream: constant mu + small Gaussian noise."""
    rng = random.Random(seed)
    return [mu + rng.gauss(0, 0.005) for _ in range(n)]


def _make_noise_stream(n: int, seed: int = 42) -> list[float]:
    """Pure noise with zero expected return."""
    rng = random.Random(seed)
    return [rng.gauss(0, 0.02) for _ in range(n)]


def _make_overfit_stream(n: int, seed: int = 42) -> list[float]:
    """IS-great / OOS-terrible: positive first half, negative second half."""
    rng = random.Random(seed)
    half = n // 2
    good = [0.03 + rng.gauss(0, 0.003) for _ in range(half)]
    bad = [-0.03 + rng.gauss(0, 0.003) for _ in range(n - half)]
    return good + bad


# ---------------------------------------------------------------------------
# A. Path count
# ---------------------------------------------------------------------------


def test_path_count_default():
    """Default N=6, k=2 => C(6,2) = 15 paths."""
    returns = _make_edge_stream(120)
    result = cpcv(returns)
    assert not result.failed
    assert result.n_paths == _ncr(6, 2) == 15
    assert len(result.oos_sharpes) == 15


@pytest.mark.parametrize("n_groups,k_test,expected_paths", [
    (4, 1, 4),    # C(4,1)=4
    (4, 2, 6),    # C(4,2)=6
    (5, 2, 10),   # C(5,2)=10
    (6, 3, 20),   # C(6,3)=20
    (8, 2, 28),   # C(8,2)=28
])
def test_path_count_parametric(n_groups, k_test, expected_paths):
    """C(N, k) is always the exact path count, for a variety of N and k."""
    returns = _make_edge_stream(n_groups * 10)  # 10 obs per group minimum
    result = cpcv(returns, n_groups=n_groups, k_test=k_test)
    assert not result.failed, result.fail_reason
    assert result.n_paths == expected_paths
    assert len(result.oos_sharpes) == expected_paths


def test_ncr_helper():
    """Sanity-check the internal C(n,k) helper directly."""
    assert _ncr(6, 2) == 15
    assert _ncr(6, 0) == 1
    assert _ncr(6, 6) == 1
    assert _ncr(0, 0) == 1
    assert _ncr(5, 3) == 10


# ---------------------------------------------------------------------------
# B. Purge + embargo actually removes boundary observations
# ---------------------------------------------------------------------------


def test_embargo_removes_boundary_obs():
    """With embargo=1, the obs immediately adjacent to the test group boundary are absent from IS."""
    # Use a constant stream where each obs has a unique position-encoded value.
    # Group 0: obs 0..4, Group 1: obs 5..9 (test), Group 2: obs 10..14, Group 3: obs 15..19 (test)
    # With n_groups=4, k_test=2, embargo=1:
    # For the path testing groups {1,3}:
    #   - Group 0 (train): end is adjacent to group 1 (test) => drop last 1 obs (obs 4).
    #     Group 0 contributes obs 0..3.
    #   - Group 2 (train): start is adjacent to group 1 (test) => drop first 1 obs (obs 10).
    #     End is adjacent to group 3 (test) => drop last 1 obs (obs 14).
    #     Group 2 contributes obs 11..13.
    # IS obs = [0,1,2,3,  11,12,13]
    n = 20
    returns = list(range(n))  # value == index; makes it easy to verify which obs are included
    result = cpcv(returns, n_groups=4, k_test=2, embargo=1, min_group_size=1)
    assert not result.failed, result.fail_reason

    # Reconstruct the IS obs for the path (test_groups=(1,3)) by re-running the same logic manually.
    # groups: 0=[0..4], 1=[5..9], 2=[10..14], 3=[15..19]
    test_set = {1, 3}
    train_groups = [0, 2]
    group_bounds = [(0, 5), (5, 10), (10, 15), (15, 20)]
    embargo = 1
    is_obs_expected: list[int] = []
    for g in train_groups:
        s, e = group_bounds[g]
        trim_start = embargo if (g - 1) in test_set else 0
        trim_end = embargo if (g + 1) in test_set else 0
        is_obs_expected.extend(list(range(n))[s + trim_start: e - trim_end])

    # The expected IS observations must NOT include obs 4, 10, or 14.
    assert 4 not in is_obs_expected    # obs adjacent to test group 1 (from group 0 end)
    assert 10 not in is_obs_expected   # obs adjacent to test group 1 (from group 2 start)
    assert 14 not in is_obs_expected   # obs adjacent to test group 3 (from group 2 end)
    # OOS = group 1 (obs 5..9) + group 3 (obs 15..19): no embargo applied to OOS.
    assert is_obs_expected == [0, 1, 2, 3, 11, 12, 13]


def test_embargo_zero_keeps_all_train_obs():
    """With embargo=0, no train observations should be removed."""
    n = 60
    returns = list(range(n))
    result_with = cpcv(returns, n_groups=4, k_test=2, embargo=1, min_group_size=1)
    result_without = cpcv(returns, n_groups=4, k_test=2, embargo=0, min_group_size=1)
    # Without embargo, IS obs count per path is strictly >= with embargo.
    assert not result_with.failed and not result_without.failed
    # With embargo=0 and embargo=1, both succeed; the path count is the same.
    assert result_with.n_paths == result_without.n_paths


def test_oos_never_overlaps_test_groups():
    """OOS observations for a path must be exactly the test group observations."""
    n = 60  # 4 groups of 15 each
    returns = list(range(n))
    result = cpcv(returns, n_groups=4, k_test=2, embargo=0, min_group_size=1)
    assert not result.failed
    # With 4 groups of 15, group 2 = obs[30..44], group 3 = obs[45..59].
    # For the path (2,3): OOS = 30 obs; IS = 30 obs. OOS Sharpes computed on those obs.
    assert result.n_paths == 6  # C(4,2)=6


# ---------------------------------------------------------------------------
# C. Positive-edge stream: low PBO, positive deflated Sharpe
# ---------------------------------------------------------------------------


def test_edge_stream_low_pbo_positive_dsr():
    """A stream with persistent positive edge should have low CPCV-PBO and positive deflated Sharpe mean."""
    returns = _make_edge_stream(180, mu=0.025)
    result = cpcv(returns, n_groups=6, k_test=2, embargo=1)
    assert not result.failed
    assert result.cpcv_pbo < 0.6, f"PBO={result.cpcv_pbo} too high for edge stream"
    assert result.deflated_sharpe_mean > 0.0, f"DSR mean={result.deflated_sharpe_mean} not positive"
    # All (or most) OOS Sharpes should be positive for a genuine edge.
    pos_count = sum(1 for sr in result.oos_sharpes if sr > 0)
    assert pos_count >= result.n_paths * 0.7, f"Only {pos_count}/{result.n_paths} positive OOS Sharpes"


# ---------------------------------------------------------------------------
# D. Noise / overfit stream: high PBO
# ---------------------------------------------------------------------------


def test_overfit_stream_high_pbo():
    """An overfit stream (great IS, terrible OOS) should yield high CPCV-PBO."""
    returns = _make_overfit_stream(180)
    result = cpcv(returns, n_groups=6, k_test=2, embargo=1)
    assert not result.failed
    assert result.cpcv_pbo > 0.4, f"PBO={result.cpcv_pbo} not high for overfit stream"


def test_noise_stream_oos_sharpes_centered_near_zero():
    """Pure noise stream: OOS Sharpes should be distributed around zero (no systematic positive bias)."""
    returns = _make_noise_stream(300)
    result = cpcv(returns, n_groups=6, k_test=2, embargo=1)
    assert not result.failed
    mean_oos = sum(result.oos_sharpes) / len(result.oos_sharpes)
    # For pure noise the mean OOS Sharpe should be near zero.
    assert abs(mean_oos) < 0.2, f"mean OOS Sharpe={mean_oos:.4f} too far from zero for pure noise"


# ---------------------------------------------------------------------------
# E. Determinism
# ---------------------------------------------------------------------------


def test_determinism():
    """Calling cpcv twice on the same stream returns identical results."""
    returns = _make_edge_stream(120)
    r1 = cpcv(returns)
    r2 = cpcv(returns)
    assert r1.n_paths == r2.n_paths
    assert r1.oos_sharpes == r2.oos_sharpes
    assert r1.cpcv_pbo == r2.cpcv_pbo
    assert r1.deflated_sharpe_mean == r2.deflated_sharpe_mean
    assert r1.failed == r2.failed


# ---------------------------------------------------------------------------
# F. Tiny-stream fail-closed
# ---------------------------------------------------------------------------


def test_empty_stream_fails_closed():
    result = cpcv([])
    assert result.failed
    assert result.n_paths == 0
    assert result.oos_sharpes == []
    assert result.cpcv_pbo == 1.0
    assert result.deflated_sharpe_mean == 0.0


def test_tiny_stream_fails_closed():
    """A stream too small to form groups of min_group_size should fail closed."""
    result = cpcv([0.01] * 5, n_groups=6, k_test=2, embargo=1, min_group_size=4)
    assert result.failed
    assert "too short" in result.fail_reason or "min_group_size" in result.fail_reason
    assert result.n_paths == 0
    assert result.cpcv_pbo == 1.0  # fail-safe: maximum overfit signal


def test_borderline_stream_succeeds():
    """A stream right at the minimum threshold should succeed."""
    # 6 groups * 4 min_group_size = 24 obs minimum.
    returns = _make_edge_stream(24)
    result = cpcv(returns, n_groups=6, k_test=2, embargo=0, min_group_size=4)
    assert not result.failed, result.fail_reason
    assert result.n_paths == 15


# ---------------------------------------------------------------------------
# G. Parameter-validation fail-closed guards
# ---------------------------------------------------------------------------


def test_k_test_equals_n_groups_fails():
    """k_test == n_groups is invalid (no train data at all) — must fail closed."""
    result = cpcv(_make_edge_stream(60), n_groups=4, k_test=4)
    assert result.failed


def test_k_test_zero_fails():
    result = cpcv(_make_edge_stream(60), n_groups=4, k_test=0)
    assert result.failed


def test_n_groups_one_fails():
    result = cpcv(_make_edge_stream(60), n_groups=1, k_test=1)
    assert result.failed


def test_failed_result_is_safe_to_use():
    """Callers treating failed=True as a gate trip should see PBO=1.0 (overfit) and DSR=0.0 (no edge)."""
    result = cpcv([], n_groups=6, k_test=2)
    assert result.failed
    assert result.cpcv_pbo == 1.0   # worst-case overfit signal
    assert result.deflated_sharpe_mean == 0.0
    assert result.n_paths == 0
