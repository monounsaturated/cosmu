"""Adversarial validation of the edge Gate — prove it is not leaky.

A leaky gate is one that reports an exploitable edge where none exists (look-ahead, a feature's own
autocorrelation, or multiple-testing it failed to deflate). We attack all three gate variants
(single-signal · aggregation ablation · cross-asset ablation) from three directions and require:

  (1) SHUFFLED label/returns  → 0 survivors (STOP)   — the permutation null
  (2) synthetic NO-EDGE data  → 0 survivors (STOP)   — the pure-noise null
  (3) a known-edge fixture    → PASS                 — the positive control (the suite CAN detect edge)

(1) is the sharp test. We take EDGE-BEARING inputs and permute each feature's values across time while
keeping every point-in-time stamp — and the entire return path — fixed (`shuffle_alt_provider` /
`shuffle_news_provider`). The marginal distribution of every feature is preserved exactly; only its
alignment to returns is destroyed. Under this null a non-leaky gate MUST STOP. Any PASS is spurious and
marks a leak to fix in the gate — never a reason to weaken this test.

These tests run offline on deterministic fixtures and are picked up by `pnpm verify` (CI), which runs the
whole `apps/engine/tests` suite.
"""

from __future__ import annotations

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research.fixtures import (
    shuffle_alt_provider,
    shuffle_news_provider,
    synthetic_ablation_inputs,
    synthetic_cross_asset_inputs,
    synthetic_gate_inputs,
)
from cosmu.research.gate import (
    evaluate_ablation,
    evaluate_cross_asset_ablation,
    evaluate_gate,
)


def _store(tmp_path, name: str) -> Store:
    # no openrouter_api_key → the whole gate runs offline (CI has no keys; the LLM is ingest-only).
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


# ---- (3) Positive control: the suite CAN pass a real edge ------------------------------------
# If these ever fail, the nulls below are meaningless (a gate that never passes trivially "rejects"
# every null). They pin that the machinery has discriminating power before we trust its STOPs.


def test_known_edge_single_signal_passes(tmp_path):
    market, provider = synthetic_gate_inputs(edge=True, seed=7)
    assert evaluate_gate(market, provider, _store(tmp_path, "edge_single")).passed


def test_known_edge_ablation_passes(tmp_path):
    market, alt, news = synthetic_ablation_inputs(edge=True, seed=7)
    assert evaluate_ablation(market, alt, news, _store(tmp_path, "edge_abl")).passed


def test_known_edge_cross_asset_passes(tmp_path):
    mbc, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    assert evaluate_cross_asset_ablation(mbc, alt, news, _store(tmp_path, "edge_xa")).passed


# ---- (2) Pure-noise null: no relationship anywhere → 0 survivors -----------------------------


def test_no_edge_single_signal_stops(tmp_path):
    market, provider = synthetic_gate_inputs(edge=False, seed=7)
    v = evaluate_gate(market, provider, _store(tmp_path, "noise_single"))
    assert not v.passed and v.reasons


def test_no_edge_ablation_stops(tmp_path):
    market, alt, news = synthetic_ablation_inputs(edge=False, seed=7)
    v = evaluate_ablation(market, alt, news, _store(tmp_path, "noise_abl"))
    assert not v.passed and v.reasons


def test_no_edge_cross_asset_stops(tmp_path):
    mbc, alt, news = synthetic_cross_asset_inputs(edge=False, seed=7)
    v = evaluate_cross_asset_ablation(mbc, alt, news, _store(tmp_path, "noise_xa"))
    assert not v.passed and v.reasons


# ---- (1) Permutation null: real edge, shuffled away → 0 survivors ----------------------------
# The strongest test. EDGE-BEARING inputs, feature values permuted across time. Marginals identical,
# return path identical; only the signal→return alignment is gone. Multiple seeds = multiple draws of
# the null, each of which the gate must reject. (Offline scans confirm 0/20 false passes for the
# single-signal gate and 0 for the ablation/cross-asset gates; these seeds regression-guard that.)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_shuffled_single_signal_stops(tmp_path, seed):
    market, provider = synthetic_gate_inputs(edge=True, seed=7)
    shuffled = shuffle_alt_provider(provider, seed=seed)
    v = evaluate_gate(market, shuffled, _store(tmp_path, f"shuf_single_{seed}"))
    assert not v.passed, f"single-signal gate PASSED on permuted noise (seed={seed}) — LEAK: {v}"
    assert v.reasons


@pytest.mark.parametrize("seed", [0, 1])
def test_shuffled_ablation_stops(tmp_path, seed):
    market, alt, news = synthetic_ablation_inputs(edge=True, seed=7)
    v = evaluate_ablation(
        market,
        shuffle_alt_provider(alt, seed=seed),
        shuffle_news_provider(news, seed=seed),
        _store(tmp_path, f"shuf_abl_{seed}"),
    )
    assert not v.passed, f"ablation gate PASSED on permuted noise (seed={seed}) — LEAK: {v}"
    assert v.reasons
    # Structural defense: the shuffled alt arm cannot out-earn the price-only baseline it filters.
    assert v.alt_return <= v.price_only_return or "not_beating_price_only" in v.reasons


@pytest.mark.parametrize("seed", [0, 1])
def test_shuffled_cross_asset_stops(tmp_path, seed):
    mbc, alt, news = synthetic_cross_asset_inputs(edge=True, seed=7)
    v = evaluate_cross_asset_ablation(
        mbc,
        shuffle_alt_provider(alt, seed=seed),
        shuffle_news_provider(news, seed=seed),
        _store(tmp_path, f"shuf_xa_{seed}"),
    )
    assert not v.passed, f"cross-asset gate PASSED on permuted noise (seed={seed}) — LEAK: {v}"
    assert v.reasons


def test_shuffle_preserves_marginals_and_breaks_alignment():
    """The permutation is an honest null: it is a pure reordering of values onto the SAME timestamps
    (same multiset of values, same stamps), so any edge it removes was alignment, not distribution."""
    _, provider = synthetic_gate_inputs(edge=True, seed=7)
    shuffled = shuffle_alt_provider(provider, seed=0)
    for key, original in provider.series.items():
        perm = shuffled.series[key]
        assert [p.ts for p in perm] == [p.ts for p in original]  # stamps fixed
        assert [p.available_at for p in perm] == [p.available_at for p in original]
        assert sorted(p.value for p in perm) == sorted(p.value for p in original)  # same multiset
        assert [p.value for p in perm] != [p.value for p in original]  # actually reordered
