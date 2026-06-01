# Gate hardening (purged/embargoed CPCV + Benjamini-Hochberg FDR) and the money-levers (execution cost
# optimization + capital rotation). Pure-math units — no DB, no network.

from __future__ import annotations

from math import comb

from cosmu.execution.costopt import FeeSchedule, FeeTier, choose_order, fee_for_volume
from cosmu.master.cv import embargo_size, purged_embargo_splits
from cosmu.master.fdr import benjamini_hochberg, bh_threshold, dsr_pvalue, survives_fdr
from cosmu.portfolio.rotation import Sleeve, is_decayed, kelly_fraction, paying_sources, rotate


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


# --- execution cost optimization ----------------------------------------------------------------

TIERS = [
    FeeTier(0, FeeSchedule(maker_bps=1.0, taker_bps=5.0)),
    FeeTier(1_000_000, FeeSchedule(maker_bps=0.0, taker_bps=4.0)),
    FeeTier(10_000_000, FeeSchedule(maker_bps=-0.5, taker_bps=3.0)),  # maker rebate at top tier
]


def test_fee_tier_routing():
    assert fee_for_volume(500, TIERS).taker_bps == 5.0
    assert fee_for_volume(2_000_000, TIERS).taker_bps == 4.0
    assert fee_for_volume(50_000_000, TIERS).maker_bps == -0.5


def test_maker_preferred_when_patient_with_rebate():
    fee = FeeSchedule(maker_bps=-0.5, taker_bps=5.0)
    plan = choose_order(20.0, fee, spread_bps=4.0, urgency=0.1, maker_fill_prob=0.9)
    assert plan.order_type == "maker"
    assert plan.expected_net_bps > 0


def test_taker_preferred_when_urgent_and_unlikely_to_fill():
    fee = FeeSchedule(maker_bps=0.0, taker_bps=2.0)
    plan = choose_order(30.0, fee, spread_bps=2.0, urgency=1.0, maker_fill_prob=0.1)
    assert plan.order_type == "market"


# --- capital rotation ---------------------------------------------------------------------------

def test_kelly_is_capped_and_nonnegative():
    assert kelly_fraction(0.1, 0.01, cap=0.25) == 0.25   # raw 10 → capped
    assert kelly_fraction(-0.1, 0.01) == 0.0             # no edge → 0
    assert kelly_fraction(0.001, 0.01, cap=0.25) == 0.1  # 0.001/0.01


def test_decay_detection():
    assert is_decayed(Sleeve("a", edge=0.01, variance=0.01, rolling_dsr=0.5))            # dsr below floor
    assert is_decayed(Sleeve("b", edge=0.01, variance=0.01, rolling_dsr=0.99, paper_live_divergence=0.9))
    assert not is_decayed(Sleeve("c", edge=0.01, variance=0.01, rolling_dsr=0.99))


def test_rotate_defunds_decayed_concentrates_and_caps_weight():
    sleeves = [
        Sleeve("win1", edge=0.05, variance=0.01, rolling_dsr=0.99),
        Sleeve("win2", edge=0.04, variance=0.01, rolling_dsr=0.98),
        Sleeve("win3", edge=0.03, variance=0.01, rolling_dsr=0.97),
        Sleeve("marg", edge=0.001, variance=0.01, rolling_dsr=0.96),  # positive but cut by concentration
        Sleeve("dead", edge=0.05, variance=0.01, rolling_dsr=0.40),   # decayed → defunded
    ]
    allocs = {a.sleeve_id: a.weight for a in rotate(sleeves, max_positions=3, kelly_cap=0.25)}
    assert allocs["dead"] == 0.0
    assert allocs["marg"] == 0.0                       # below concentration cut
    assert sum(allocs.values()) <= 1.0 + 1e-9
    assert all(allocs[s] > 0 for s in ("win1", "win2", "win3"))


def test_paying_sources_keeps_only_payers():
    sleeves = [
        Sleeve("a", edge=0.05, variance=0.01, rolling_dsr=0.99,
               source_attribution={"news": 0.02, "funding": -0.01}),
        Sleeve("b", edge=0.04, variance=0.01, rolling_dsr=0.98,
               source_attribution={"news": 0.01, "funding": 0.005}),
    ]
    pay = paying_sources(sleeves)
    assert "news" in pay and pay["news"] > 0
    assert "funding" not in pay   # net marginal across sleeves is negative → dead weight, cut it
