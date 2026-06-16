# trial_stats_for_cohort (master/trials): effective trial count when K correlated strategies just registered.
# A correlated grid of K near-duplicate variants is NOT K independent tests — the effective count is
# K/(1+(K-1)*rho_bar). This module replaces the raw K contribution with K_eff in the global count, making
# the gate FAIRER (less Type-II over-rejection) without loosening it for independent hypotheses.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.trials import register_trial, trial_stats, trial_stats_for_cohort


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/trials.sqlite3", openrouter_api_key=None))


def _register_n(store: Store, n: int, base_sr: float = 0.05) -> None:
    """Register N trials, alternating Sharpe so there is non-zero variance."""
    for i in range(n):
        register_trial(store, base_sr * (1 + i % 3), source="test", label=f"t{i}")


def test_independent_variants_same_as_raw_count(tmp_path):
    # rho_bar=0 → K_eff=K → no haircut → identical to plain trial_stats.
    store = _store(tmp_path)
    _register_n(store, 20)
    plain = trial_stats(store)
    corrected = trial_stats_for_cohort(store, 5, 0.0)
    assert corrected.count == plain.count  # no haircut when correlation is zero


def test_correlated_grid_reduces_effective_count(tmp_path):
    # 10 historical + 10 perfectly-correlated grid variants (rho=1): K_eff = 10/(1+9*1) = 1.
    # Effective count = 10_hist + 1 = 11 (< 20 raw).
    store = _store(tmp_path)
    _register_n(store, 10)              # 10 historical trials
    _register_n(store, 10, base_sr=0.03)  # 10 current-grid trials
    # total in DB = 20; K=10, rho=1.0 → K_eff=1 → n_adjusted = 10 + 1 = 11
    result = trial_stats_for_cohort(store, 10, 1.0)
    assert result.count == 11


def test_high_rho_haircut_formula(tmp_path):
    # K=4, rho=0.75: K_eff = 4/(1+3*0.75) = 4/3.25 ≈ 1.23 → rounds to 1.
    # N_hist=6 (10 total − 4 current), N_adjusted = 6 + 1.23 ≈ 7.
    store = _store(tmp_path)
    _register_n(store, 6)
    _register_n(store, 4, base_sr=0.03)
    result = trial_stats_for_cohort(store, 4, 0.75)
    assert result.count == 7  # 6 + round(4/3.25) = 6 + 1


def test_none_rho_falls_back_to_raw(tmp_path):
    # None rho → conservative fallback → raw global count.
    store = _store(tmp_path)
    _register_n(store, 12)
    plain = trial_stats(store)
    fallback = trial_stats_for_cohort(store, 4, None)
    assert fallback.count == plain.count


def test_single_variant_no_haircut(tmp_path):
    # k=1 → K_eff=1 → no change (can't compute rho for a single variant anyway).
    store = _store(tmp_path)
    _register_n(store, 5)
    plain = trial_stats(store)
    result = trial_stats_for_cohort(store, 1, 0.9)
    assert result.count == plain.count


def test_sr_variance_preserved(tmp_path):
    # The sr_variance (cross-sectional Sharpe variance) is read from the FULL global trials set unchanged;
    # only count is adjusted. This ensures SR0 is still calibrated to the real distribution of Sharpes.
    store = _store(tmp_path)
    _register_n(store, 20)
    plain = trial_stats(store)
    corrected = trial_stats_for_cohort(store, 10, 0.8)
    assert corrected.sr_variance == plain.sr_variance  # variance unchanged
    assert corrected.count < plain.count               # but count is reduced


def test_count_floored_at_one(tmp_path):
    # Edge case: 1 trial in DB, k=1, rho=None → should return count=1, not 0.
    store = _store(tmp_path)
    register_trial(store, 0.05, source="test", label="t0")
    result = trial_stats_for_cohort(store, 1, None)
    assert result.count == 1
