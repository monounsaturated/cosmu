# INDEPENDENT-REFERENCE PARITY for the hand-rolled Gate statistics — the moat's trust layer.
#
# scorer.py (PSR / DSR / SR0 expected-max-Sharpe deflation / CSCV-PBO) and cpcv.py are bespoke numeric code
# that decides whether a strategy is funded. There is NO drop-in library for the Deflated Sharpe Ratio, so the
# oracle here is a SECOND, independent implementation of the SAME published formulas (Bailey & López de Prado,
# "The Deflated Sharpe Ratio", 2014; Bailey & López de Prado, "The Sharpe Ratio Efficient Frontier", 2012;
# Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting", 2017) written against
# scipy.stats / numpy rather than the engine's statistics.NormalDist + hand math. If the two agree across many
# regimes and edge cases, the production formula is what it claims to be.
#
# This mirrors tests/test_fdr_parity.py (BH-FDR pinned against a frozen oracle) and tests/test_spearman_parity.py
# (Spearman pinned against scipy): a frozen reference, parity over hand-picked edge cases, and a fuzz sweep.
#
# TOLERANCE: PSR shares Φ with the production path so it is bit-identical (atol 0); SR0 / DSR cross statistics.
# NormalDist.inv_cdf against scipy.norm.ppf, which round differently at the last bit, so the bar is 1e-12 (still
# ~10 orders of magnitude tighter than the 0.95 gate). CSCV-PBO is a rational fraction and is bit-identical.
#
# TEST-ONLY: this file imports the production stats and re-derives them independently; it changes NO Gate
# constant and NO production stat logic. VERDICT (this revision): PARITY HOLDS — every stat matches its
# independent scipy/numpy reference within tolerance across every regime probed; nothing is xfailed.

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pytest
from scipy import stats

from cosmu.master.scorer import (
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    deflated_sharpe_prob,
    effective_trials,
    expected_max_sharpe,
    probabilistic_sharpe,
)

# Euler–Mascheroni γ, as it appears in the Gaussian-extreme (Gumbel) approximation to E[max of N draws].
_EULER_GAMMA = 0.5772156649015329

# PSR shares the normal CDF with production → exact; SR0/DSR cross inv_cdf libraries → ~1e-16 in practice.
_FP = 1e-12


# === frozen INDEPENDENT reference — scipy/numpy re-derivation of the published formulas ====================


def _ref_psr(sr_hat: float, n_obs: int, skew: float, kurtosis: float, sr_benchmark: float) -> float:
    """PSR (Bailey & López de Prado 2012, eq. for the Probabilistic Sharpe Ratio):

        PSR(SR*) = Φ[ (SR_hat − SR*)·√(n−1) / √(1 − γ3·SR_hat + ((γ4−1)/4)·SR_hat²) ]

    γ3 = skewness, γ4 = full (non-excess) kurtosis (Gaussian = 3). Independent of the engine: Φ via
    scipy.stats.norm.cdf, with the same n<2 and non-positive-variance guards the formula implies.
    """
    if n_obs < 2:
        return 0.0
    variance_term = 1.0 - skew * sr_hat + ((kurtosis - 1.0) / 4.0) * sr_hat * sr_hat
    if variance_term <= 0:
        return 0.0
    z = (sr_hat - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(variance_term)
    return float(stats.norm.cdf(z))


def _ref_expected_max_sharpe(sr_variance: float, n_trials: float) -> float:
    """SR0 — expected maximum of n_trials i.i.d. N(0, sr_variance) per-obs Sharpes, via the Gaussian-extreme
    (Gumbel) approximation used in the Deflated Sharpe Ratio (Bailey & López de Prado 2014):

        E[max_N] ≈ √V · [ (1 − γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]

    γ = Euler–Mascheroni constant, Z⁻¹ = standard-normal quantile (scipy.stats.norm.ppf here, independent of
    the engine's statistics.NormalDist.inv_cdf). Floored at 0 and a no-op for N ≤ 1 / V ≤ 0, matching the
    formula's domain (a benchmark cannot go negative, which would perversely make the DSR easier to clear).
    """
    if n_trials <= 1.0 or sr_variance <= 0:
        return 0.0
    sigma = math.sqrt(sr_variance)
    a = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
    b = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
    return max(0.0, sigma * ((1.0 - _EULER_GAMMA) * a + _EULER_GAMMA * b))


def _ref_effective_trials(n_trials: float, sr_correlation: float | None) -> float:
    """Effective independent-trial count under average pairwise correlation ρ̄: N_eff = N / (1 + (N−1)·ρ̄).
    ρ̄ clamped to [0, 1]; None / ρ̄≤0 / N≤1 ⇒ N unchanged. Independent re-statement of the haircut."""
    if sr_correlation is None:
        return n_trials
    rho = min(1.0, max(0.0, sr_correlation))
    if n_trials <= 1.0 or rho <= 0.0:
        return n_trials
    return n_trials / (1.0 + (n_trials - 1.0) * rho)


def _ref_lo_sr_variance(sr_hat: float, n_obs: int) -> float:
    """Analytic null sampling variance of a Sharpe estimate (Lo 2002): Var(SR_hat) ≈ (1 + ½·SR²)/(n−1).
    Used as SR0's spread when no cross-sectional trial variance is supplied."""
    if n_obs < 2:
        return 0.0
    return (1.0 + 0.5 * sr_hat * sr_hat) / (n_obs - 1)


def _ref_deflated_sharpe_prob(metrics: BacktestMetrics, trials: TrialStats) -> float:
    """DSR end-to-end (Bailey & López de Prado 2014): PSR evaluated against the trial-count-inflated benchmark
    SR0, where the trial count is the EFFECTIVE independent count (correlation haircut on the raw count).
    Built purely from the reference pieces above, so a divergence isolates which production piece drifted."""
    sr_hat = float(metrics.sharpe_per_obs)
    if trials.sr_variance is not None:
        sr_variance = max(trials.sr_variance, 0.0)
    else:
        sr_variance = _ref_lo_sr_variance(sr_hat, metrics.n_obs)
    n_trials = float(max(trials.count, metrics.trials_counted, 1))
    n_eff = _ref_effective_trials(n_trials, trials.sr_correlation)
    sr0 = _ref_expected_max_sharpe(sr_variance, n_eff)
    return _ref_psr(sr_hat, metrics.n_obs, float(metrics.skew), float(metrics.kurtosis), sr0)


def _ref_cscv_pbo(config_block_returns: list[list[float]], s_blocks: int = 8) -> float:
    """CSCV Probability of Backtest Overfitting (Bailey, Borwein, López de Prado & Zhu 2017), independently
    re-derived with numpy block-means: split the timeline into S blocks, enumerate every balanced IS/OOS
    split, pick the IS-best config, take its OOS rank → relative rank ω → logit; PBO is the fraction of
    splits where logit ≤ 0 (IS-best lands at/below the OOS median). Same guards as production (≥2 configs,
    S forced even and ≥2, ≥1 obs/block) so the domain is identical."""
    n_configs = len(config_block_returns)
    if n_configs < 2:
        return 1.0
    length = min(len(series) for series in config_block_returns)
    s = max(2, min(s_blocks, length))
    if s % 2:
        s -= 1
    if s < 2:
        return 1.0
    block_size = length // s
    if block_size < 1:
        return 1.0

    arr = np.array([series[: s * block_size] for series in config_block_returns], dtype=float)
    block_means = arr.reshape(n_configs, s, block_size).mean(axis=2)  # (n_configs, s)

    block_ids = list(range(s))
    overfit = 0
    total = 0
    for is_blocks in combinations(block_ids, s // 2):
        is_set = set(is_blocks)
        oos_blocks = [b for b in block_ids if b not in is_set]
        is_perf = block_means[:, list(is_blocks)].mean(axis=1)
        oos_perf = block_means[:, oos_blocks].mean(axis=1)
        best = int(np.argmax(is_perf))
        rank = 1 + int(np.sum(oos_perf < oos_perf[best]))  # 1 (worst) .. n_configs (best)
        omega = rank / (n_configs + 1)
        logit = math.log(omega / (1.0 - omega)) if 0.0 < omega < 1.0 else (-math.inf if omega <= 0 else math.inf)
        if logit <= 0.0:
            overfit += 1
        total += 1
    return overfit / total if total else 1.0


def _metrics(sr_hat: float, n_obs: int, skew: float, kurtosis: float, trials_counted: int = 1) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return="0", sharpe="1", sortino="1", max_drawdown="0", win_rate="0.5", num_trades=100,
        sharpe_per_obs=str(sr_hat), skew=str(skew), kurtosis=str(kurtosis), n_obs=n_obs, trials_counted=trials_counted,
    )


# === PSR parity ===========================================================================================

# (sr_hat, n_obs, skew, kurtosis, sr_benchmark) across normal, fat-tailed, tiny-n, zero-edge, leptokurtic.
_PSR_REGIMES = [
    (0.10, 100, 0.0, 3.0, 0.0),       # textbook normal
    (0.04225765, 1622, 1.442218, 22.259682, 0.0),  # the real DeFi-flow row (high kurtosis) from test_strategy_dsr_prob
    (0.20, 10, -0.5, 5.0, 0.05),      # short sample, negative skew, fat tails, non-zero benchmark
    (0.05, 2, 0.0, 3.0, 0.0),         # n == 2 (the smallest n the formula admits)
    (0.00, 50, 0.0, 3.0, 0.0),        # zero edge → PSR == 0.5 exactly
    (-0.08, 500, 0.3, 8.0, 0.0),      # negative Sharpe
    (0.15, 3000, 2.0, 30.0, 0.10),    # long sample, very fat tails, demanding benchmark
]


@pytest.mark.parametrize("sr_hat,n_obs,skew,kurt,bench", _PSR_REGIMES)
def test_psr_matches_reference(sr_hat, n_obs, skew, kurt, bench):
    prod = probabilistic_sharpe(sr_hat, n_obs, skew, kurt, bench)
    ref = _ref_psr(sr_hat, n_obs, skew, kurt, bench)
    assert prod == pytest.approx(ref, abs=_FP), (sr_hat, n_obs, skew, kurt, bench, prod, ref)


def test_psr_guards():
    # n < 2 → 0.0 (cannot estimate a Sharpe variance).
    assert probabilistic_sharpe(0.1, 1, 0.0, 3.0, 0.0) == 0.0 == _ref_psr(0.1, 1, 0.0, 3.0, 0.0)
    # variance_term <= 0 (sub-Gaussian kurtosis + large skew·SR) → 0.0, not a NaN/exception.
    assert probabilistic_sharpe(2.0, 100, 2.0, 0.0, 0.0) == 0.0 == _ref_psr(2.0, 100, 2.0, 0.0, 0.0)


# === SR0 (expected-max-Sharpe deflation term) parity ======================================================

# (sr_variance, n_trials) — incl. fractional N (post-correlation-haircut), N at/below the N<=1 floor, V==0.
_SR0_REGIMES = [
    (0.01, 2), (0.01, 10), (0.005, 100), (0.02, 1000), (0.01, 50_000), (0.01, 1_000_000),
    (0.01, 1.5),   # fractional effective-trial count
    (0.01, 1.0),   # floor: N == 1 → 0.0
    (0.01, 0.7),   # below floor
    (0.0, 10),     # zero variance → 0.0
]


@pytest.mark.parametrize("sr_variance,n_trials", _SR0_REGIMES)
def test_expected_max_sharpe_matches_reference(sr_variance, n_trials):
    prod = expected_max_sharpe(sr_variance, n_trials)
    ref = _ref_expected_max_sharpe(sr_variance, n_trials)
    assert prod == pytest.approx(ref, abs=_FP), (sr_variance, n_trials, prod, ref)


def test_sr0_high_trial_count_grows_monotonically():
    # Sanity on the deflation direction: more trials ⇒ a higher bar to clear (independent of parity).
    prev = -1.0
    for n in (2, 10, 100, 1000, 10_000, 100_000):
        cur = expected_max_sharpe(0.01, n)
        assert cur >= prev
        prev = cur


def test_effective_trials_haircut_matches_reference():
    for n, rho in [(100.0, None), (100.0, 0.0), (100.0, 0.3), (100.0, 0.9), (100.0, 1.0),
                   (1.0, 0.5), (50.0, -0.2), (50.0, 1.5)]:
        assert effective_trials(n, rho) == pytest.approx(_ref_effective_trials(n, rho), abs=_FP), (n, rho)


# === DSR end-to-end parity ================================================================================


def test_dsr_matches_reference_fuzz():
    """The headline guarantee: production DSR == the independent scipy/numpy DSR across thousands of random
    regimes — varying n_obs, trials, skew, kurtosis, the supplied-vs-analytic variance path, AND the
    correlation haircut — the whole pipeline (Lo-variance → effective-trials → SR0 → PSR) at once."""
    rng = np.random.default_rng(20260625)
    max_diff = 0.0
    for _ in range(4000):
        sr_hat = float(rng.uniform(-0.12, 0.22))
        n_obs = int(rng.integers(20, 3000))
        skew = float(rng.uniform(-1.5, 1.5))
        kurt = float(rng.uniform(3.0, 30.0))
        n_trials = int(rng.integers(1, 250))
        # Half the draws exercise the supplied cross-sectional variance, half the Lo (2002) analytic null.
        sr_variance = float(rng.uniform(0.0005, 0.02)) if rng.random() < 0.5 else None
        sr_corr = float(rng.choice([0.0, 0.1, 0.3, 0.5, 0.9])) if rng.random() < 0.7 else None

        metrics = _metrics(sr_hat, n_obs, skew, kurt, trials_counted=n_trials)
        trials = TrialStats(count=n_trials, sr_variance=sr_variance, sr_correlation=sr_corr)

        prod = deflated_sharpe_prob(metrics, trials)
        ref = _ref_deflated_sharpe_prob(metrics, trials)
        max_diff = max(max_diff, abs(prod - ref))
        assert prod == pytest.approx(ref, abs=_FP), (sr_hat, n_obs, skew, kurt, n_trials, sr_variance, sr_corr, prod, ref)
    assert max_diff < _FP, f"worst |prod-ref| = {max_diff:.3e}"


def test_dsr_edge_cases():
    # n_obs < 2 → PSR floor of 0.0 regardless of trials.
    m = _metrics(0.1, 1, 0.0, 3.0)
    assert deflated_sharpe_prob(m, TrialStats(count=10, sr_variance=0.01)) == _ref_deflated_sharpe_prob(m, TrialStats(count=10, sr_variance=0.01))
    # Single trial (count=1) → SR0 == 0 → DSR collapses to plain PSR vs benchmark 0.
    m = _metrics(0.08, 500, 0.2, 4.0)
    t = TrialStats(count=1, sr_variance=0.01)
    assert deflated_sharpe_prob(m, t) == pytest.approx(_ref_deflated_sharpe_prob(m, t), abs=_FP)
    assert deflated_sharpe_prob(m, t) == pytest.approx(probabilistic_sharpe(0.08, 500, 0.2, 4.0, 0.0), abs=_FP)
    # Very high trial count crushes the probability.
    m = _metrics(0.06, 800, 0.0, 4.0)
    t = TrialStats(count=100_000, sr_variance=0.01)
    assert deflated_sharpe_prob(m, t) == pytest.approx(_ref_deflated_sharpe_prob(m, t), abs=_FP)


# === CSCV-PBO (the CSCV rank-logit) parity ================================================================


def _genuine_edge_blocks(n_configs: int, length: int, seed: int) -> list[list[float]]:
    """Persistent cross-config edge: config c earns 0.001·c every block — IS ranking transfers to OOS."""
    g = np.random.default_rng(seed)
    return [list(0.001 * c + g.normal(0, 0.004, length)) for c in range(n_configs)]


def _overfit_blocks(n_configs: int, length: int, seed: int) -> list[list[float]]:
    """IS-great / OOS-terrible per config (positive first half, negative second) — the overfit signature."""
    g = np.random.default_rng(seed)
    half = length // 2
    out = []
    for _ in range(n_configs):
        out.append(list(np.concatenate([0.03 + g.normal(0, 0.003, half), -0.03 + g.normal(0, 0.003, length - half)])))
    return out


def _noise_blocks(n_configs: int, length: int, seed: int) -> list[list[float]]:
    g = np.random.default_rng(seed)
    return [list(g.normal(0, 0.02, length)) for _ in range(n_configs)]


@pytest.mark.parametrize("name,builder", [
    ("genuine_edge", _genuine_edge_blocks),
    ("overfit", _overfit_blocks),
    ("noise", _noise_blocks),
])
@pytest.mark.parametrize("n_configs,length", [(2, 80), (3, 16), (6, 96), (8, 200)])
def test_cscv_pbo_matches_reference(name, builder, n_configs, length):
    cfg = builder(n_configs, length, seed=hash((name, n_configs, length)) % (2**31))
    prod = cscv_pbo(cfg)
    ref = _ref_cscv_pbo(cfg)
    # Rational fraction over an identical enumeration ⇒ bit-identical.
    assert prod == ref, (name, n_configs, length, prod, ref)


def test_cscv_pbo_matches_reference_fuzz():
    rng = np.random.default_rng(424242)
    for _ in range(400):
        n_configs = int(rng.integers(2, 9))
        length = int(rng.integers(16, 200))
        kind = int(rng.integers(0, 3))
        builder = (_noise_blocks, _genuine_edge_blocks, _overfit_blocks)[kind]
        cfg = builder(n_configs, length, int(rng.integers(0, 2**31)))
        assert cscv_pbo(cfg) == _ref_cscv_pbo(cfg), (n_configs, length, kind)


def test_cscv_pbo_guards():
    # < 2 configs cannot be evaluated → maximally overfit (fail-closed).
    assert cscv_pbo([[0.01] * 50]) == 1.0 == _ref_cscv_pbo([[0.01] * 50])
    assert cscv_pbo([]) == 1.0 == _ref_cscv_pbo([])
    # A genuine, persistently-separated edge drives PBO to its floor (0.0); both agree.
    edge = _genuine_edge_blocks(6, 120, seed=1)
    assert cscv_pbo(edge) == _ref_cscv_pbo(edge)
    assert cscv_pbo(edge) <= 0.5  # an edge whose IS ranking transfers is, by construction, NOT overfit
