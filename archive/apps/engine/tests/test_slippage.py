# Tests for cosmu.data.slippage: SlippageModel distribution draws, StressResult correctness,
# fragility flag logic, zero-std determinism, turnover scaling, and thick- vs thin-edge behaviour.

from __future__ import annotations

import math
import random
import statistics

import pytest

from cosmu.data.slippage import SlippageModel, StressResult, stress_returns


# ---------------------------------------------------------------------------
# Synthetic return-stream helpers
# ---------------------------------------------------------------------------


def _thick_edge_stream(n: int = 500, seed: int = 1) -> list[float]:
    """A strong edge: high positive mean, low noise — survives heavy slippage easily."""
    rng = random.Random(seed)
    # ~3 bp/day net drift with 80 bp/day vol → Sharpe ≈ 2+ annualised
    return [rng.gauss(0.003, 0.008) for _ in range(n)]


def _thin_edge_stream(n: int = 500, seed: int = 2) -> list[float]:
    """A marginal edge: tiny positive mean, moderate noise — barely positive at mean slippage."""
    rng = random.Random(seed)
    # ~0.3 bp/day drift with 100 bp/day vol → Sharpe ≈ 0.5 annualised; slippage variance kills it
    return [rng.gauss(0.0003, 0.010) for _ in range(n)]


def _flat_stream(n: int = 300) -> list[float]:
    """Zero-return stream: all zeros."""
    return [0.0] * n


# ---------------------------------------------------------------------------
# SlippageModel.draw — basic properties
# ---------------------------------------------------------------------------


def test_draw_is_nonnegative():
    """Slippage draws must never be negative (you can't execute better than the best quote)."""
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    rng = random.Random(99)
    draws = [model.draw(rng) for _ in range(1000)]
    assert all(d >= 0.0 for d in draws), "All slippage draws must be non-negative"


def test_zero_std_draw_is_deterministic():
    """zero std_bps → draw == mean_bps + participation term, independent of rng state."""
    model = SlippageModel(mean_bps=7.0, std_bps=0.0)
    rng1 = random.Random(1)
    rng2 = random.Random(999)
    d1 = model.draw(rng1)
    d2 = model.draw(rng2)
    assert d1 == pytest.approx(d2, abs=1e-12), "zero-std draws must be identical regardless of seed"


def test_participation_term_scales_draw():
    """Higher participation increases the expected draw by the stated bps-per-pct rate."""
    model = SlippageModel(mean_bps=5.0, std_bps=0.0, participation_bps_per_pct=0.5)
    rng = random.Random(0)
    low = model.draw(rng, participation_pct=0.0)
    high = model.draw(rng, participation_pct=10.0)
    assert high > low, "higher participation → higher (or equal) slippage draw"
    assert high == pytest.approx(low + 0.5 * 10.0, abs=1e-9)


def test_nonzero_std_produces_variance():
    """std_bps > 0 means distinct draws have non-trivial spread."""
    model = SlippageModel(mean_bps=5.0, std_bps=4.0)
    rng = random.Random(42)
    draws = [model.draw(rng) for _ in range(500)]
    assert statistics.pstdev(draws) > 0.5, "std_bps=4 should produce measurable spread in draws"


# ---------------------------------------------------------------------------
# stress_returns — zero std reproduces flat-bps result
# ---------------------------------------------------------------------------


def test_zero_std_reproduces_flat_bps():
    """With std_bps=0, every Monte-Carlo path is identical and equals the base outcome."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=0.0)
    result = stress_returns(returns, turnover_per_period=0.1, model=model, draws=50, seed=7)

    # All path Sharpes must equal the base Sharpe.
    for sr in result.sharpe_distribution:
        assert sr == pytest.approx(result.base_sharpe, abs=1e-10), (
            "zero-std paths must all equal the base Sharpe"
        )
    # p05 must also equal base.
    assert result.p05_sharpe == pytest.approx(result.base_sharpe, abs=1e-10)


# ---------------------------------------------------------------------------
# stress_returns — determinism
# ---------------------------------------------------------------------------


def test_deterministic_for_fixed_seed():
    """Identical inputs + seed → identical StressResult."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    r1 = stress_returns(returns, turnover_per_period=0.05, model=model, draws=100, seed=42)
    r2 = stress_returns(returns, turnover_per_period=0.05, model=model, draws=100, seed=42)
    assert r1.sharpe_distribution == r2.sharpe_distribution
    assert r1.total_return_distribution == r2.total_return_distribution
    assert r1.p05_sharpe == r2.p05_sharpe
    assert r1.fragile == r2.fragile


def test_different_seeds_produce_different_paths():
    """Different seeds → different (non-trivially different) Sharpe distributions for nonzero std."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    r1 = stress_returns(returns, turnover_per_period=0.05, model=model, draws=50, seed=1)
    r2 = stress_returns(returns, turnover_per_period=0.05, model=model, draws=50, seed=2)
    assert r1.sharpe_distribution != r2.sharpe_distribution


# ---------------------------------------------------------------------------
# stress_returns — turnover scaling
# ---------------------------------------------------------------------------


def test_higher_turnover_increases_slippage_drag():
    """Doubling turnover should worsen (lower) both the mean Sharpe and p05 Sharpe."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    lo = stress_returns(returns, turnover_per_period=0.05, model=model, draws=200, seed=42)
    hi = stress_returns(returns, turnover_per_period=0.30, model=model, draws=200, seed=42)

    mean_sr_lo = statistics.fmean(lo.sharpe_distribution)
    mean_sr_hi = statistics.fmean(hi.sharpe_distribution)
    assert mean_sr_hi < mean_sr_lo, "higher turnover → lower mean Sharpe across paths"
    assert hi.p05_sharpe < lo.p05_sharpe, "higher turnover → lower p05 Sharpe"


def test_zero_turnover_means_no_additional_cost():
    """At zero turnover there is no additional slippage cost, so all paths equal the input stream's metrics."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=10.0, std_bps=5.0)
    result = stress_returns(returns, turnover_per_period=0.0, model=model, draws=100, seed=42)

    # With zero turnover, additional_cost = slip_frac * 0 * 2 = 0 on every bar, so paths = input returns.
    expected_sr = _annualized_sharpe_ref(returns)
    for sr in result.sharpe_distribution:
        assert sr == pytest.approx(expected_sr, abs=1e-10)


# ---------------------------------------------------------------------------
# stress_returns — thick edge: NOT fragile
# ---------------------------------------------------------------------------


def test_thick_edge_is_not_fragile():
    """A strong edge should survive worst-case slippage variance without flipping fragile."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=5.0)
    result = stress_returns(returns, turnover_per_period=0.1, model=model, draws=200, seed=42)

    assert result.base_sharpe > 1.0, "thick edge should have base Sharpe > 1 before stress"
    assert not result.fragile, "thick edge must NOT be flagged fragile under 5+/-5 bps slippage"
    assert result.p05_sharpe > 0.0, "thick edge p05 Sharpe must remain positive"


# ---------------------------------------------------------------------------
# stress_returns — thin edge: IS fragile under high variance
# ---------------------------------------------------------------------------


def test_thin_edge_is_fragile_under_variance():
    """A marginal edge that barely survives mean slippage must flip fragile under realistic variance."""
    returns = _thin_edge_stream()
    # High std relative to the tiny edge: 8 bps spread + 6 bps std with moderate turnover will kill a ~0.5 SR edge.
    model = SlippageModel(mean_bps=4.0, std_bps=6.0)
    result = stress_returns(returns, turnover_per_period=0.15, model=model, draws=200, seed=42)

    # The thin edge might be positive at mean slippage but the p05 should turn it negative / halved.
    assert result.fragile, (
        f"thin edge must be flagged fragile; p05_sharpe={result.p05_sharpe:.4f}, "
        f"base_sharpe={result.base_sharpe:.4f}"
    )


# ---------------------------------------------------------------------------
# stress_returns — StressResult fields are coherent
# ---------------------------------------------------------------------------


def test_stress_result_fields_are_coherent():
    """Basic structural checks: correct draw count, sorted p05 matches, base matches zero-std path."""
    returns = _thick_edge_stream()
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    result = stress_returns(returns, turnover_per_period=0.1, model=model, draws=100, seed=42)

    assert result.draws == 100
    assert len(result.sharpe_distribution) == 100
    assert len(result.total_return_distribution) == 100

    # p05 should be at or below the 5th percentile of the distribution.
    sorted_sr = sorted(result.sharpe_distribution)
    p05_idx = max(0, int(math.floor(0.05 * 100)) - 1)
    assert result.p05_sharpe == pytest.approx(sorted_sr[p05_idx], abs=1e-12)


def test_empty_returns_returns_zero_result():
    """Empty return stream → empty distributions, no crash."""
    model = SlippageModel(mean_bps=5.0, std_bps=3.0)
    result = stress_returns([], turnover_per_period=0.1, model=model)
    assert result.sharpe_distribution == []
    assert not result.fragile


def test_turnover_list_length_mismatch_raises():
    """Mismatched turnover list length must raise a ValueError."""
    returns = [0.001] * 10
    model = SlippageModel(mean_bps=5.0, std_bps=0.0)
    with pytest.raises(ValueError, match="length"):
        stress_returns(returns, turnover_per_period=[0.1] * 5, model=model)


# ---------------------------------------------------------------------------
# Reference helper (mirrors backtest._sharpe without importing it)
# ---------------------------------------------------------------------------


def _annualized_sharpe_ref(returns: list[float], periods_per_year: float = 365.0) -> float:
    if len(returns) < 2:
        return 0.0
    std = statistics.pstdev(returns)
    if std == 0.0:
        return 0.0
    return statistics.fmean(returns) / std * math.sqrt(periods_per_year)
