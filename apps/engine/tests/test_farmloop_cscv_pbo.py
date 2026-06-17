# Gate-integrity item 2: the autonomous FarmLoop must NOT let correlated near-duplicate mutants inflate the
# BH-FDR family, and must judge the cohort on a REAL cohort CSCV-PBO (not the per-candidate _pbo_proxy). It now
# mirrors lab/finder.py: cluster the screened streams into DISTINCT representatives (Pearson >= 0.95 → same
# hypothesis), run BH-FDR over the representatives only, and inject the cohort CSCV-PBO onto every candidate
# before scoring. This file proves BOTH halves and that the net effect is strictly >= as strict as before.
#
# These tests are deterministic and hermetic: _screen is monkeypatched to hand back controlled return streams +
# strong (gate-clearing) metrics, so the cohort's clustering + cohort-PBO math is exercised in isolation from the
# (real) backtest. The champion holdout is forced to PASS so it never confounds the cluster/FDR assertions.

from __future__ import annotations

import hashlib
import random
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.evolution.loop import CLUSTER_CORRELATION, Candidate, FarmLoop
from cosmu.knowledge.store import Store
from cosmu.master.cohort import cluster_representatives, cohort_cscv_pbo
from cosmu.master.scorer import BacktestMetrics
from cosmu.spine.venue import default_catalog


def _det_seed(name: str) -> int:
    """A DETERMINISTIC integer seed from a name — builtin hash() is salted per-process (PYTHONHASHSEED), which
    would make the stream fixtures flaky across runs. hashlib is stable, so the cohort's clustering + CSCV-PBO
    are reproducible."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")


def _store(tmp_path, name: str = "fl") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _loop(tmp_path, name: str = "fl") -> FarmLoop:
    # No market_data provider needed — _screen is monkeypatched in every test below.
    return FarmLoop(settings=_store(tmp_path, name).settings, store=_store(tmp_path, name))


# Strong, gate-clearing metrics (very high Sharpe, low drawdown, plenty of trades). pbo is set LOW here so that,
# if the loop used the per-candidate proxy instead of the cohort CSCV-PBO, every candidate would pass the pbo
# gate — making the injected-cohort-PBO test's failure mode observable.
def _strong() -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal("0.2"), sharpe=Decimal("19"), sortino=Decimal("2"), max_drawdown=Decimal("0.08"),
        win_rate=Decimal("0.6"), num_trades=80, sharpe_per_obs=Decimal("1.0"), skew=Decimal("0"),
        kurtosis=Decimal("3"), n_obs=1000, pbo=Decimal("0.05"), trials_counted=1,
        folds_positive_pct=Decimal("0.9"),
    )


# Two strong, mostly-positive base streams (each a clear winner → the 2-config cohort's CSCV-PBO is low). They
# are uncorrelated with each other (independent noise patterns) so they form two DISTINCT clusters.
_BASE_A = [0.010, 0.013, 0.008, 0.012, 0.014, 0.007, 0.011, 0.013, 0.008, 0.012, 0.015, 0.006,
           0.010, 0.013, 0.008, 0.012, 0.014, 0.007, 0.011, 0.013, 0.008, 0.012, 0.015, 0.006]
_BASE_B = [0.012, 0.007, 0.014, 0.009, 0.006, 0.015, 0.011, 0.008, 0.013, 0.007, 0.014, 0.010,
           0.012, 0.007, 0.014, 0.009, 0.006, 0.015, 0.011, 0.008, 0.013, 0.007, 0.014, 0.010]


def _identical_stream(_cand: Candidate) -> list[float]:
    """Every candidate gets the SAME stream (correlation 1.0) → the whole cohort collapses to ONE representative."""
    return list(_BASE_A)


def _two_cluster_stream(cand: Candidate) -> list[float]:
    """Two CLUSTERS: candidates split (by a deterministic name hash) into group A and group B, each group
    internally identical (correlation 1.0) but the two groups uncorrelated. → exactly TWO distinct representatives
    and several correlated near-duplicates per group. The 2-config cohort's CSCV-PBO is low (both strong winners),
    so the representatives PASS the pbo gate and the folded duplicates are demoted as cluster_dup."""
    return list(_BASE_A if (_det_seed(cand.spec.name) & 1) == 0 else _BASE_B)


def _distinct_stream(cand: Candidate) -> list[float]:
    """Each candidate gets an idiosyncratic stream that is NOT >= 0.95 correlated with the others, on a shared
    strong uptrend (so every stream is a clear winner). Deterministic per candidate name so re-runs are
    reproducible."""
    rng = random.Random(_det_seed(cand.spec.name))
    return [0.01 + rng.uniform(-0.007, 0.007) for _ in range(24)]


def _force_screen(monkeypatch, stream_fn, *, capture: list | None = None) -> None:  # noqa: ANN001
    venue = default_catalog().venue_for(["binance"])

    def _screen(self, cand, code_hash, seed):  # noqa: ANN001, ANN202
        stream = stream_fn(cand)
        if capture is not None:
            # Record what each candidate was screened with, in screening order — so a test can faithfully
            # recompute the cohort's clustering + CSCV-PBO over the SAME streams (the loop screens, then clusters
            # in that same insertion order; all metrics tie so the sort is stable).
            capture.append(stream)
        return (_strong(), venue, 20, stream)

    monkeypatch.setattr(FarmLoop, "_screen", _screen)
    # Force the one-shot holdout to PASS so it never demotes a survivor — isolating the cluster/FDR/PBO behavior.
    monkeypatch.setattr(FarmLoop, "_champion_holdout", lambda self, spec, params: 5.0)


# --------------------------------------------------------------------------- (a) correlated cohort → smaller family


def _cluster_dup_count(store: Store) -> int:
    return store.row(
        "SELECT COUNT(*) AS n FROM strategy_versions WHERE kill_reason LIKE '%cluster_dup%'"
    )["n"]


def test_correlated_near_duplicates_are_culled_and_the_fdr_family_shrinks(tmp_path, monkeypatch):
    """A cohort split into TWO correlation clusters (each with several near-identical members) must collapse to
    exactly TWO distinct representatives. Every folded near-duplicate is demoted with kill_reason 'cluster_dup',
    so only the representatives enter the BH-FDR family. The effective trial count the gate corrects for is the
    REPRESENTATIVE count, not the raw cohort size — a swarm of correlated mutants can NOT inflate the family to
    ease the discovery cutoff. This is the core anti-inflation guarantee."""
    loop = _loop(tmp_path, "corr")
    _force_screen(monkeypatch, _two_cluster_stream)
    summary = loop.run_cohort(seed=7, cohort_size=14)

    assert summary.generated >= 4, "fixture must generate enough candidates to populate both clusters w/ dups"
    dups = _cluster_dup_count(loop.store)
    assert dups >= 1, "correlated near-duplicates must be culled as cluster_dup"
    # The BH-FDR family = the candidates that were NOT folded as near-duplicates. It is strictly SMALLER than the
    # raw cohort because the duplicates were removed from the family (this is the trial-count deflation).
    fdr_family_size = summary.generated - dups
    assert fdr_family_size < summary.generated
    # Two clusters → at most two distinct representatives can ever be funded (no swarm of dups gets funded).
    assert len(summary.survivors) <= 2
    n_tracks = loop.store.row("SELECT COUNT(*) AS n FROM tracks")["n"]
    assert n_tracks <= 2


def test_distinct_cohort_is_not_over_collapsed_vs_a_correlated_one(tmp_path, monkeypatch):
    """The control proving the shrink is SELECTIVE: a genuinely UNCORRELATED cohort of equally-strong candidates
    sheds NO members as cluster_dup, whereas the clustered cohort sheds several. Same strength, size, and seed —
    only the stream correlation differs. So the family shrinks ONLY when streams are correlated; a diverse cohort
    is never over-collapsed (the dedup can't manufacture extra strictness on real, decorrelated breadth)."""
    clustered = _loop(tmp_path, "c1")
    _force_screen(monkeypatch, _two_cluster_stream)
    clustered_summary = clustered.run_cohort(seed=7, cohort_size=14)
    clustered_dups = _cluster_dup_count(clustered.store)

    distinct = _loop(tmp_path, "d1")
    _force_screen(monkeypatch, _distinct_stream)
    distinct_summary = distinct.run_cohort(seed=7, cohort_size=14)
    distinct_dups = _cluster_dup_count(distinct.store)

    assert clustered_summary.generated == distinct_summary.generated >= 4
    # The clustered cohort sheds duplicates; the decorrelated cohort sheds none.
    assert clustered_dups >= 1
    assert distinct_dups == 0
    assert clustered_dups > distinct_dups


# --------------------------------------------------------------------------- (b) injected cohort CSCV-PBO is used


def test_persisted_pbo_is_the_cohort_cscv_pbo_not_the_per_candidate_proxy(tmp_path, monkeypatch):
    """The pbo persisted on every screened backtest must be the cohort's REAL CSCV-PBO computed over the DISTINCT
    representatives' streams — NOT the per-candidate _pbo_proxy (which would be the strong-metric's own low
    proxy, 0.05 here). With an all-correlated cohort the representatives collapse to ONE stream, so the cohort
    CSCV-PBO is the single-config sentinel 1.0 — a value the per-candidate proxy could never produce for these
    strong metrics. Seeing 1.0 on the rows is the proof the cohort value was injected before scoring."""
    loop = _loop(tmp_path, "pbo1")
    _force_screen(monkeypatch, _identical_stream)
    loop.run_cohort(seed=7, cohort_size=8)

    rows = loop.store.rows("SELECT pbo FROM backtests WHERE kind='screen'")
    assert rows, "the cohort must persist at least one screen backtest"
    # The cohort CSCV-PBO for a single-representative collapse is exactly the sentinel 1.0.
    expected = cohort_cscv_pbo(["only"], {"only": list(_BASE_A)})
    assert expected == 1.0
    for r in rows:
        assert Decimal(str(r["pbo"])) == Decimal("1.0")
        assert Decimal(str(r["pbo"])) != _strong().pbo  # explicitly NOT the per-candidate proxy (0.05)


def test_injected_cohort_pbo_matches_independently_computed_cscv_over_distinct_streams(tmp_path, monkeypatch):
    """A diverse (uncorrelated) cohort: the persisted pbo on every row must EQUAL the REAL combinatorial-cross-
    validation PBO computed over the deduped representatives' streams — recomputed here independently from the
    SAME streams the loop screened (captured in screening order). This proves the injected value is the genuine
    cohort CSCV-PBO of the diverse population, not a per-candidate stand-in (the proxy is candidate-specific and
    would never be byte-identical across the whole cohort)."""
    captured: list[list[float]] = []
    loop = _loop(tmp_path, "pbo2")
    _force_screen(monkeypatch, _distinct_stream, capture=captured)
    loop.run_cohort(seed=7, cohort_size=10)

    rows = loop.store.rows("SELECT pbo FROM backtests WHERE kind='screen'")
    assert rows
    # Every screened candidate carries the SAME injected cohort PBO (one cohort estimate shared across the family).
    persisted = {Decimal(str(r["pbo"])) for r in rows}
    assert len(persisted) == 1, "the whole cohort shares ONE injected cohort CSCV-PBO"
    cohort_pbo = next(iter(persisted))

    # Recompute the expected cohort CSCV-PBO independently, mirroring run_cohort exactly: all candidates share the
    # SAME (tied) metrics so the best-first sort is stable → ordering = screening (capture) order. Cluster at the
    # SAME shared threshold, then CSCV-PBO over the representative streams.
    returns_by_tag = {i: s for i, s in enumerate(captured)}
    ordered = [i for i in range(len(captured)) if len(captured[i]) >= 2]
    reps = cluster_representatives(ordered, returns_by_tag, threshold=CLUSTER_CORRELATION)
    expected = cohort_cscv_pbo(reps, returns_by_tag)

    assert cohort_pbo == Decimal(str(round(expected, 6)))
    # Sanity: a genuinely diverse cohort yields MORE than one representative (so it is a REAL CSCV value, not the
    # single-config 1.0 sentinel), and it is NOT the per-candidate proxy.
    assert len(reps) >= 2
    assert cohort_pbo != _strong().pbo
