# Portfolio-axis crowding instrument (master/signal_crowding): SIGNAL-correlation clamp (Khandani-Lo, 0.70 cap),
# fractional-Kelly self-sizing from the deflated edge, and CAPACITY as a RANKED feature (never a disqualifier).
# Propose-only + PURE: nothing here gates a strategy or moves money.
from __future__ import annotations

import math
import random

from cosmu.master.signal_crowding import (
    FULL_EXPOSURE,
    MIN_EXPOSURE,
    SIGNAL_CROWDING_CAP,
    PortfolioCell,
    capacity_score,
    portfolio_exposure_factors,
    signal_crowding_factors,
)


def _corr_signal(base: list[float], jitter: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [x + rng.gauss(0, jitter) for x in base]


# ── capacity_score: a RANKED feature, never a disqualifier ─────────────────────────────────────────────────────


def test_capacity_niche_fillable_outranks_deep_no_moat_market():
    # A niche-but-fillable alt ($8M/day) is a better SOLO game than a deep no-moat major ($9B/day): higher rank.
    deep = capacity_score(10_000.0, 9_000_000_000.0)   # fillable, no moat → BASE only
    niche = capacity_score(10_000.0, 8_000_000.0)       # desk-invisible but fillable → niche bonus
    assert 0.0 < deep < niche <= 1.0


def test_capacity_unfillable_thin_market_scores_low_but_not_killed():
    # If our size is a large fraction of a too-thin book, fillability collapses → low score. But it is a SCORE in
    # [0,1] (a rank), never a hard reject: the function returns a number, it does not raise or disqualify.
    thin = capacity_score(1_000_000.0, 2_000_000.0)  # 50% of daily volume — way past the participation wall
    assert thin == 0.0  # ranked to the bottom, still just a number (no exception, no kill)


def test_capacity_unknown_volume_degrades_to_zero():
    assert capacity_score(10_000.0, 0.0) == 0.0
    assert capacity_score(10_000.0, -5.0) == 0.0


def test_capacity_is_bounded_unit_interval():
    for notional, vol in [(0.0, 1e6), (1e3, 5e6), (5e4, 1e7), (1e6, 1e12)]:
        s = capacity_score(notional, vol)
        assert 0.0 <= s <= 1.0


# ── signal_crowding_factors: cluster on SIGNAL correlation, scale down redundant members ───────────────────────


def test_crowd_scaled_down_decorrelated_kept_full():
    rng = random.Random(11)
    base = [rng.gauss(0, 1.0) for _ in range(80)]
    a = _corr_signal(base, 0.02, 1)   # ~identical signals (cluster)
    b = _corr_signal(base, 0.02, 2)
    c = _corr_signal(base, 0.02, 3)
    indep = [rng.gauss(0, 1.0) for _ in range(80)]  # decorrelated
    cells = [
        PortfolioCell("a", a, deflated_edge=0.96, capacity=0.5),
        PortfolioCell("b", b, deflated_edge=0.95, capacity=0.5),
        PortfolioCell("c", c, deflated_edge=0.97, capacity=0.5),  # highest edge×cap → kept
        PortfolioCell("indep", indep, deflated_edge=0.96, capacity=0.5),
    ]
    f = signal_crowding_factors(cells)
    assert f["indep"] == FULL_EXPOSURE         # decorrelated → untouched
    assert f["c"] == FULL_EXPOSURE             # cluster representative kept at full
    assert f["a"] < FULL_EXPOSURE and f["b"] < FULL_EXPOSURE
    assert f["a"] >= MIN_EXPOSURE and f["b"] >= MIN_EXPOSURE
    # 3-member cluster → non-best members deploy ~1/3 (floored).
    assert abs(f["a"] - max(MIN_EXPOSURE, 1 / 3)) < 1e-9


def test_capacity_tips_which_cluster_member_is_kept():
    # Two near-identical signals, near-equal edge. The cell on the NICHE (higher-capacity) market is kept at full;
    # the deep-market twin is scaled down. Capacity changes WHERE the book deploys ("where you play beats how well").
    rng = random.Random(5)
    base = [rng.gauss(0, 1.0) for _ in range(80)]
    deep = _corr_signal(base, 0.01, 1)
    niche = _corr_signal(base, 0.01, 2)
    cells = [
        PortfolioCell("deep", deep, deflated_edge=0.965, capacity=0.50),   # slightly higher edge, no moat
        PortfolioCell("niche", niche, deflated_edge=0.958, capacity=0.90),  # lower edge, high capacity
    ]
    f = signal_crowding_factors(cells)
    assert f["niche"] == FULL_EXPOSURE          # capacity won the keep despite lower edge
    assert f["deep"] < FULL_EXPOSURE


def test_no_op_below_two_cells_or_no_overlap():
    one = [PortfolioCell("solo", [0.1] * 50, deflated_edge=0.96)]
    assert signal_crowding_factors(one) == {"solo": FULL_EXPOSURE}
    empties = [PortfolioCell("a", [], deflated_edge=0.96), PortfolioCell("b", [], deflated_edge=0.96)]
    assert signal_crowding_factors(empties) == {"a": FULL_EXPOSURE, "b": FULL_EXPOSURE}


def test_decorrelated_book_is_honest_no_op():
    cells = [PortfolioCell(f"c{i}", [random.Random(i).gauss(0, 1) for _ in range(80)], deflated_edge=0.96)
             for i in range(4)]
    # Independent signals → no cluster → all full exposure.
    f = signal_crowding_factors(cells)
    assert all(v == FULL_EXPOSURE for v in f.values())


# ── portfolio_exposure_factors: combined Kelly × crowding + transparency report ────────────────────────────────


def test_combined_factor_is_kelly_times_crowding():
    rng = random.Random(7)
    base = [rng.gauss(0, 1.0) for _ in range(80)]
    cells = [
        PortfolioCell("a", _corr_signal(base, 0.01, 1), deflated_edge=0.96, capacity=0.5),
        PortfolioCell("b", _corr_signal(base, 0.01, 2), deflated_edge=0.94, capacity=0.5),
        PortfolioCell("indep", [rng.gauss(0, 1) for _ in range(80)], deflated_edge=0.98, capacity=0.5),
    ]
    rep = portfolio_exposure_factors(cells)
    for cf in rep.factors.values():
        assert abs(cf.combined - cf.kelly * cf.crowding) < 1e-12
    assert rep.n_cells == 3
    assert rep.n_clusters == 1
    assert rep.n_capped == 1                       # exactly one redundant member scaled down
    assert rep.corr_cap == SIGNAL_CROWDING_CAP
    # The decorrelated cell is never capped; its combined == its kelly.
    indep = rep.factors["indep"]
    assert indep.crowding == FULL_EXPOSURE and abs(indep.combined - indep.kelly) < 1e-12


def test_report_no_op_for_single_cell():
    rep = portfolio_exposure_factors([PortfolioCell("solo", [0.1] * 50, deflated_edge=0.96)])
    assert rep.n_clusters == 0 and rep.n_capped == 0
    assert math.isnan(rep.avg_signal_correlation)
    assert rep.factors["solo"].crowding == FULL_EXPOSURE
