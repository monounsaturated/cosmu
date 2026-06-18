# Gate hardening (purged/embargoed CPCV + Benjamini-Hochberg FDR) and the money-levers (execution cost
# optimization + capital rotation). Pure-math units — no DB, no network.

from __future__ import annotations

from math import comb

from cosmu.master.cv import embargo_size, purged_embargo_splits
from cosmu.master.fdr import benjamini_hochberg, bh_threshold, dsr_pvalue, survives_fdr
from cosmu.portfolio.rotation import Track, is_decayed, paying_sources, select_tracks

# --- CPCV --------------------------------------------------------------------------------------

def test_cpcv_split_count_is_combinatorial():
    splits = purged_embargo_splits(120, n_groups=6, n_test_groups=2)
    assert len(splits) == comb(6, 2) == 15


def test_cpcv_train_and_test_are_disjoint():
    for train, test in purged_embargo_splits(120, n_groups=6, n_test_groups=2):
        assert not (set(train) & set(test))


def test_cpcv_purges_label_window_and_embargo():
    # horizon 3 + embargo means indices right before AND after a test block are dropped from train
    splits = purged_embargo_splits(120, n_groups=6, n_test_groups=1, label_horizon=3)
    train, test = splits[1]  # an interior test block
    lo, hi = min(test), max(test)
    emb = embargo_size(120, label_horizon=3)
    # nothing in train within the purge window before lo or the embargo window after hi
    assert all(not (lo - 3 <= t < lo) for t in train)
    assert all(not (hi < t <= hi + emb) for t in train)


def test_embargo_size_floor():
    assert embargo_size(100, embargo_pct=0.01, label_horizon=1, min_embargo=5) == 5   # 1% of 100 = 1 → floor 5
    assert embargo_size(2000, embargo_pct=0.01, label_horizon=1) == 20                # 1% dominates


# --- BH-FDR ------------------------------------------------------------------------------------

def test_bh_rejects_strong_and_spares_noise():
    pvals = [0.001, 0.002, 0.5, 0.6, 0.9]
    mask = benjamini_hochberg(pvals, q=0.10)
    assert mask[0] and mask[1]
    assert not any(mask[2:])


def test_bh_all_noise_rejects_nothing():
    assert not any(benjamini_hochberg([0.4, 0.6, 0.8, 0.95], q=0.10))


def test_dsr_pvalue_and_survives():
    assert abs(dsr_pvalue(0.97) - 0.03) < 1e-9
    pvals = [0.01, 0.02, 0.5, 0.7]
    assert survives_fdr(0.01, pvals, q=0.10)
    assert not survives_fdr(0.5, pvals, q=0.10)
    assert bh_threshold([0.9, 0.95], q=0.10) == 0.0  # nothing qualifies


# NOTE: the maker/taker order-choice optimizer (cosmu/execution/costopt.py) was DELETED — the Bar model is
# OHLCV-only (no depth to evaluate a maker fill rule), so the cost path is ALWAYS-TAKER and there was no live
# caller. Fee realism now lives in the per-asset resolver (spine/asset_fees.py) — see test_asset_fees.py.


# --- per-track lifecycle (standalone paper, NO pooled wallet) -----------------------------

def test_decay_detection():
    assert is_decayed(Track("a", rolling_dsr=0.5))                              # dsr below floor
    assert is_decayed(Track("b", rolling_dsr=0.99, sim_live_divergence=0.9))    # sim/live divergence
    assert not is_decayed(Track("c", rolling_dsr=0.99))


def test_select_tracks_funds_each_survivor_standalone_and_defunds_decayed():
    tracks = [
        Track("win1", rolling_dsr=0.99),
        Track("win2", rolling_dsr=0.98),
        Track("win3", rolling_dsr=0.97),
        Track("dead", rolling_dsr=0.40),   # decayed → defunded
    ]
    verdict = {v.version_id: v for v in select_tracks(tracks)}
    # NO pooled competition: every healthy survivor stays funded on its own standalone track.
    assert all(verdict[s].funded for s in ("win1", "win2", "win3"))
    assert not verdict["dead"].funded and "defunded" in verdict["dead"].reason


def test_select_tracks_optional_concurrent_ceiling():
    tracks = [Track(f"t{i}", rolling_dsr=0.99) for i in range(5)]
    funded = [v.version_id for v in select_tracks(tracks, max_tracks=3) if v.funded]
    assert len(funded) == 3   # operational ceiling on concurrent tracks (cost/throughput, not capital weighting)


def test_paying_sources_keeps_only_payers():
    tracks = [
        Track("a", rolling_dsr=0.99, source_attribution={"news": 0.02, "funding": -0.01}),
        Track("b", rolling_dsr=0.98, source_attribution={"news": 0.01, "funding": 0.005}),
    ]
    pay = paying_sources(tracks)
    assert "news" in pay and pay["news"] > 0
    assert "funding" not in pay   # net marginal across tracks is negative → dead weight, cut it
