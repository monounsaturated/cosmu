# The funded-track BOOK backtest WITH vs WITHOUT the portfolio-axis signal-crowding clamp (playbook bridge #7).
# Pins the claim: the clamp keeps total return ~similar while CUTTING max drawdown, and improves the risk-adjusted
# (recovery) factor. The book simulator is no-pooled-wallet (standalone equal slices); these tests also pin that.
from __future__ import annotations

from cosmu.master.crowding_backtest import compare_clamp, simulate_book
from cosmu.master.signal_crowding import portfolio_exposure_factors

# The report script owns the deterministic, fully-disclosed methodology book (synthetic ⇒ tests/methodology only,
# never the app). Importing it here keeps the test and the report numbers on ONE source of truth.
from scripts.crowding_clamp_backtest import build_demo_book


# ── simulate_book: no pooled wallet, honest aggregation ────────────────────────────────────────────────────────


def test_simulate_book_sums_standalone_slices():
    # Two flat cells (0 return) → book equity constant at one slice each; no drawdown, no return.
    res = simulate_book({"a": [0.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0]}, {"a": 1.0, "b": 1.0})
    assert res.total_return == 0.0
    assert res.max_drawdown == 0.0
    assert res.equity_curve[0] == 2.0  # two slices of 1.0


def test_factor_below_one_deploys_less_not_reallocated():
    # A cell at factor 0.5 deploys half its slice; the rest is cash (NOT handed to the other cell — no pool).
    up = [0.10, 0.10]  # +10%/bar
    full = simulate_book({"x": up}, {"x": 1.0})
    half = simulate_book({"x": up}, {"x": 0.5})
    # full: 1.0 → 1.21 (+21%). half: 0.5 deployed → 0.605, +0.5 cash = 1.105 (+10.5%).
    assert abs(full.total_return - 0.21) < 1e-9
    assert abs(half.total_return - 0.105) < 1e-9


def test_max_drawdown_measures_book_peak_to_trough():
    # +20%, then −50%: peak 1.2, trough 0.6 → DD 0.5.
    res = simulate_book({"x": [0.20, -0.50]}, {"x": 1.0})
    assert abs(res.max_drawdown - 0.5) < 1e-9


# ── compare_clamp on the disclosed methodology book (pinned seed) ──────────────────────────────────────────────


def test_clamp_cuts_drawdown_keeps_return():
    cells, returns_by_cell = build_demo_book()
    cmp = compare_clamp(cells, returns_by_cell)

    # 1) The clamp found the crowded cluster and scaled its redundant members down (4-member crowd → 3 scaled).
    assert cmp.n_clusters == 1
    assert cmp.n_capped == 3

    # 2) Max drawdown is materially REDUCED (robust across 20 noise seeds: 48–57%; pinned ≈ 52%).
    assert cmp.with_clamp.max_drawdown < cmp.without_clamp.max_drawdown
    dd_reduction = 1.0 - cmp.with_clamp.max_drawdown / cmp.without_clamp.max_drawdown
    assert dd_reduction > 0.30

    # 3) Total return stays ~similar — the redundant copies add little NET return (gains round-trip in the crash).
    #    Absolute delta is the honest measure (the relative metric is unstable near a ~zero baseline return).
    assert abs(cmp.return_delta) < 0.03  # within 3 percentage points (pinned ≈ -0.5pp)

    # 4) Risk-adjusted return IMPROVES (lower DD for ~same return).
    assert cmp.with_clamp.recovery_factor > cmp.without_clamp.recovery_factor


def test_capacity_decides_the_kept_cluster_member():
    # The niche-market crowd member (highest capacity rank) is kept at full exposure over its deeper, higher-edge
    # twins — capacity tips WHERE the book deploys.
    cells, _ = build_demo_book()
    rep = portfolio_exposure_factors(cells)
    kept = [cf.cell_id for cf in rep.factors.values() if cf.is_cluster_representative]
    assert kept == ["momo_niche"]
    # Every other crowd member is scaled below full exposure.
    for cid in ("momo_btc", "momo_eth", "momo_sol"):
        assert rep.factors[cid].crowding < 1.0


def test_book_is_deterministic():
    a = compare_clamp(*build_demo_book())
    b = compare_clamp(*build_demo_book())
    assert a.with_clamp.total_return == b.with_clamp.total_return
    assert a.without_clamp.max_drawdown == b.without_clamp.max_drawdown
