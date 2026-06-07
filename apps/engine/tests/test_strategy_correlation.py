# intent: deterministic offline tests for cosmu.master.strategy_correlation — the pure diagnostic helper
# that flags REDUNDANT funded/candidate strategy tracks. No I/O, no DB, no LLM. All synthetic data.

from __future__ import annotations

import math

import pytest

from cosmu.master.strategy_correlation import (
    MIN_OVERLAP,
    REDUNDANCY_THRESHOLD,
    CorrelationReport,
    PairCorrelation,
    _rank,
    _spearman,
    pairwise_correlation,
    redundant_strategy_ids,
    summarise,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 60  # bars — comfortably above MIN_OVERLAP


def _iid_stream(seed: int, n: int = _N) -> list[float]:
    """Pseudo-random ± returns — cheap, deterministic, no numpy needed."""
    state = seed
    result = []
    for _ in range(n):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        val = ((state & 0xFFFF) / 32768.0 - 1.0) * 0.02  # in (-2%, +2%)
        result.append(val)
    return result


def _correlated_stream(base: list[float], noise_scale: float, seed: int) -> list[float]:
    """Mix `base` with iid noise — produces a stream correlated with `base`."""
    noise = _iid_stream(seed, len(base))
    return [b + noise_scale * n for b, n in zip(base, noise)]


# ---------------------------------------------------------------------------
# Unit: rank function
# ---------------------------------------------------------------------------


def test_rank_no_ties():
    vals = [3.0, 1.0, 2.0]
    r = _rank(vals)
    assert r[0] == 3.0 and r[1] == 1.0 and r[2] == 2.0


def test_rank_all_ties():
    r = _rank([5.0, 5.0, 5.0])
    assert r == [2.0, 2.0, 2.0]  # average rank of positions 1,2,3 = 2.0


def test_rank_partial_ties():
    # [1, 1, 3] → positions 0,1 tie at rank 1.5; position 2 gets rank 3
    r = _rank([1.0, 1.0, 3.0])
    assert r[0] == 1.5 and r[1] == 1.5 and r[2] == 3.0


def test_rank_empty():
    assert _rank([]) == []


# ---------------------------------------------------------------------------
# Unit: Spearman computation
# ---------------------------------------------------------------------------


def test_spearman_perfect_monotone():
    xs = list(range(30))
    assert _spearman(xs, xs) == pytest.approx(1.0, abs=1e-9)


def test_spearman_perfect_anti_monotone():
    xs = list(range(30))
    assert _spearman(xs, list(reversed(xs))) == pytest.approx(-1.0, abs=1e-9)


def test_spearman_unrelated_is_near_zero():
    a = _iid_stream(1, 200)
    b = _iid_stream(999, 200)
    rho = _spearman(a, b)
    # With 200 independent draws, |ρ| should be well below the redundancy threshold
    assert abs(rho) < REDUNDANCY_THRESHOLD


def test_spearman_degenerate_constant_input():
    assert math.isnan(_spearman([1.0] * 30, list(range(30))))


def test_spearman_single_obs_returns_nan():
    assert math.isnan(_spearman([0.0], [0.0]))


# ---------------------------------------------------------------------------
# Integration: pairwise_correlation — core scenarios
# ---------------------------------------------------------------------------


def test_two_highly_correlated_tracks_are_flagged_redundant():
    base = _iid_stream(42, _N)
    # near-clone: tiny noise → very high ρ
    clone = _correlated_stream(base, noise_scale=0.05, seed=7)
    report = pairwise_correlation({"alpha": base, "beta": clone})
    assert len(report.pairs) == 1
    pair = report.pairs[0]
    assert pair.strategy_a == "alpha" and pair.strategy_b == "beta"
    assert pair.redundant is True
    assert pair.correlation >= REDUNDANCY_THRESHOLD
    assert len(report.redundant_pairs) == 1
    assert {"alpha", "beta"} == set(report.clusters)
    assert report.clusters["alpha"] == report.clusters["beta"]  # same cluster


def test_two_independent_tracks_are_not_flagged():
    a = _iid_stream(1, _N)
    b = _iid_stream(2, _N)
    report = pairwise_correlation({"strat_a": a, "strat_b": b})
    assert len(report.redundant_pairs) == 0
    assert report.clusters == {}


def test_anti_correlated_tracks_are_not_flagged_by_default():
    xs = list(range(_N))
    ys = list(reversed(xs))
    # ρ = -1.0; |ρ| = 1.0 which IS >= threshold, so redundant=True (anti-correlated IS redundant)
    report = pairwise_correlation({"long": xs, "short": ys})
    pair = report.pairs[0]
    assert pair.redundant is True  # |ρ| >= REDUNDANCY_THRESHOLD
    assert pair.correlation == pytest.approx(-1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Integration: multi-strategy clustering
# ---------------------------------------------------------------------------


def test_three_strategies_two_redundant_one_independent():
    base = _iid_stream(10, _N)
    clone = _correlated_stream(base, noise_scale=0.05, seed=11)
    independent = _iid_stream(999, _N)
    report = pairwise_correlation({"base": base, "clone": clone, "indep": independent})
    # exactly one redundant pair: base <-> clone
    assert len(report.redundant_pairs) == 1
    rp = report.redundant_pairs[0]
    assert {rp.strategy_a, rp.strategy_b} == {"base", "clone"}
    # "indep" should not appear in clusters
    assert "indep" not in report.clusters
    # base and clone share a cluster
    assert report.clusters["base"] == report.clusters["clone"]


def test_three_strategies_all_redundant_form_one_cluster():
    base = _iid_stream(5, _N)
    c1 = _correlated_stream(base, noise_scale=0.05, seed=13)
    c2 = _correlated_stream(base, noise_scale=0.05, seed=17)
    report = pairwise_correlation({"s1": base, "s2": c1, "s3": c2})
    # all three should be in one cluster
    assert len(set(report.clusters.values())) == 1
    assert len(report.clusters) == 3


def test_four_strategies_two_independent_clusters():
    base_a = _iid_stream(1, _N)
    clone_a = _correlated_stream(base_a, noise_scale=0.05, seed=2)
    base_b = _iid_stream(999, _N)
    clone_b = _correlated_stream(base_b, noise_scale=0.05, seed=1000)
    report = pairwise_correlation({"a1": base_a, "a2": clone_a, "b1": base_b, "b2": clone_b})
    # two distinct redundancy clusters
    cluster_ids = set(report.clusters.values())
    assert len(cluster_ids) == 2
    # a1 and a2 share a cluster; b1 and b2 share a cluster; the two clusters differ
    assert report.clusters["a1"] == report.clusters["a2"]
    assert report.clusters["b1"] == report.clusters["b2"]
    assert report.clusters["a1"] != report.clusters["b1"]


# ---------------------------------------------------------------------------
# Integration: insufficient overlap
# ---------------------------------------------------------------------------


def test_short_streams_produce_nan_not_flagged():
    # streams shorter than MIN_OVERLAP → NaN, not redundant (even if the tiny subset looks correlated)
    xs = list(range(MIN_OVERLAP - 1))
    ys = list(range(MIN_OVERLAP - 1))
    report = pairwise_correlation({"x": xs, "y": ys})
    pair = report.pairs[0]
    assert math.isnan(pair.correlation)
    assert pair.redundant is False
    assert pair.overlap == MIN_OVERLAP - 1


def test_exactly_min_overlap_is_accepted():
    xs = list(range(MIN_OVERLAP))
    ys = list(range(MIN_OVERLAP))
    report = pairwise_correlation({"x": xs, "y": ys})
    pair = report.pairs[0]
    assert not math.isnan(pair.correlation)
    assert pair.overlap == MIN_OVERLAP


# ---------------------------------------------------------------------------
# Integration: single strategy — no pairs
# ---------------------------------------------------------------------------


def test_single_strategy_produces_empty_report():
    report = pairwise_correlation({"solo": _iid_stream(1, _N)})
    assert report.pairs == ()
    assert report.redundant_pairs == ()
    assert report.clusters == {}
    assert math.isnan(report.average_pairwise_correlation)


def test_empty_streams_dict_produces_empty_report():
    report = pairwise_correlation({})
    assert report.pairs == ()
    assert math.isnan(report.average_pairwise_correlation)


# ---------------------------------------------------------------------------
# Integration: custom thresholds
# ---------------------------------------------------------------------------


def test_custom_redundancy_threshold_honored():
    base = _iid_stream(42, _N)
    # moderate noise → moderate ρ (say 0.6-ish)
    moderate = _correlated_stream(base, noise_scale=0.5, seed=7)
    report_strict = pairwise_correlation({"a": base, "b": moderate}, redundancy_threshold=0.95)
    report_loose = pairwise_correlation({"a": base, "b": moderate}, redundancy_threshold=0.3)
    # with a very strict threshold the pair may not be flagged
    pair_strict = report_strict.pairs[0]
    pair_loose = report_loose.pairs[0]
    # the ρ is the same regardless of threshold
    assert pair_strict.correlation == pytest.approx(pair_loose.correlation, abs=1e-9)
    # loose threshold flags it; strict does not (assuming ρ is between 0.3 and 0.95)
    if 0.3 <= abs(pair_loose.correlation) < 0.95:
        assert pair_loose.redundant is True
        assert pair_strict.redundant is False


# ---------------------------------------------------------------------------
# Integration: average_pairwise_correlation
# ---------------------------------------------------------------------------


def test_average_pairwise_correlation_is_mean_of_valid_rhos():
    base = _iid_stream(1, _N)
    clone = _correlated_stream(base, noise_scale=0.05, seed=2)
    report = pairwise_correlation({"a": base, "b": clone})
    assert not math.isnan(report.average_pairwise_correlation)
    # with just one pair, avg == that pair's ρ
    assert report.average_pairwise_correlation == pytest.approx(report.pairs[0].correlation, abs=1e-9)


# ---------------------------------------------------------------------------
# Integration: redundant_strategy_ids helper
# ---------------------------------------------------------------------------


def test_redundant_strategy_ids_returns_correct_set():
    base = _iid_stream(1, _N)
    clone = _correlated_stream(base, noise_scale=0.05, seed=2)
    independent = _iid_stream(999, _N)
    report = pairwise_correlation({"base": base, "clone": clone, "indep": independent})
    ids = redundant_strategy_ids(report)
    assert ids == frozenset({"base", "clone"})
    assert "indep" not in ids


def test_redundant_strategy_ids_empty_when_no_redundancy():
    a = _iid_stream(1, _N)
    b = _iid_stream(2, _N)
    report = pairwise_correlation({"a": a, "b": b})
    assert redundant_strategy_ids(report) == frozenset()


# ---------------------------------------------------------------------------
# Integration: summarise (smoke test — not parsing, just no crash + keywords)
# ---------------------------------------------------------------------------


def test_summarise_no_redundancy():
    a = _iid_stream(1, _N)
    b = _iid_stream(2, _N)
    report = pairwise_correlation({"a": a, "b": b})
    text = summarise(report)
    assert "decorrelated" in text.lower() or "no redundant" in text.lower()


def test_summarise_with_redundancy():
    base = _iid_stream(42, _N)
    clone = _correlated_stream(base, noise_scale=0.05, seed=7)
    report = pairwise_correlation({"alpha": base, "beta": clone})
    text = summarise(report)
    assert "REDUNDANT" in text
    assert "alpha" in text and "beta" in text


# ---------------------------------------------------------------------------
# Invariants: propose-only — no DB, no side effects
# ---------------------------------------------------------------------------


def test_module_has_no_store_import():
    """The strategy_correlation module must not import cosmu.knowledge.store (propose-only invariant)."""
    import importlib
    import sys

    mod_name = "cosmu.master.strategy_correlation"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import importlib.util

    spec = importlib.util.find_spec(mod_name)
    assert spec is not None, "module not found"
    src = spec.origin
    with open(src) as f:
        content = f.read()
    assert "cosmu.knowledge.store" not in content, "strategy_correlation must not import the store"
    assert "Store" not in content, "strategy_correlation must not reference Store"


def test_pairwise_correlation_is_deterministic():
    """Same inputs → identical output, always."""
    streams = {f"s{i}": _iid_stream(i, _N) for i in range(5)}
    r1 = pairwise_correlation(streams)
    r2 = pairwise_correlation(streams)
    assert r1.pairs == r2.pairs
    assert r1.redundant_pairs == r2.redundant_pairs
    assert r1.clusters == r2.clusters
    assert r1.average_pairwise_correlation == r2.average_pairwise_correlation
