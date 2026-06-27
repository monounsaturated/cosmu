# Time-axis decay monitor (research/decay_monitor) — the pheromone-evaporation backtest study. Covers the pure,
# deterministic, CAUSAL analytics (the exp(-Δt/τ) kernel, the τ = backtest-edge-half-life fit, the forward-
# confirmation reset, the two policies, the book aggregation, the risk-adjusted metrics), the method-validation
# verdict on the synthetic panel (decay WINS when the edge dies past zero, ≈TIE when it persists / is re-confirmed),
# the portfolio_snapshots loader, and the design-only live multiplier. No network, no LLM, gate constants untouched.

from __future__ import annotations

import math

from cosmu.config.settings import PAPER_MIN_FORWARD_DSR, Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.research.decay_monitor import (
    CONFIRM_MIN_OBS,
    TrackSeries,
    book_returns,
    decay_weights,
    decayed_weights,
    edge_half_life,
    evaluate_book,
    hold_until_fail_weights,
    is_forward_confirmation,
    live_decay_multiplier,
    load_tracks_from_store,
    pheromone_weight,
    run_study,
    synthetic_panel,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/decay.sqlite3", openrouter_api_key=None))


# --- the evaporation kernel ----------------------------------------------------------------------------------


def test_pheromone_weight_is_the_exp_decay_kernel():
    # τ None / non-positive / non-finite ⇒ no evaporation (a non-decaying trail keeps full size)
    assert pheromone_weight(10.0, None) == 1.0
    assert pheromone_weight(10.0, 0.0) == 1.0
    assert pheromone_weight(10.0, -3.0) == 1.0
    assert pheromone_weight(10.0, math.inf) == 1.0
    # exp(-Δt/τ): full at Δt=0, e⁻¹ at Δt=τ, monotone decreasing in Δt
    assert pheromone_weight(0.0, 20.0) == 1.0
    assert math.isclose(pheromone_weight(20.0, 20.0), math.exp(-1.0), rel_tol=1e-9)
    assert pheromone_weight(40.0, 20.0) < pheromone_weight(20.0, 20.0) < pheromone_weight(5.0, 20.0)
    assert 0.0 < pheromone_weight(1000.0, 20.0) <= 1.0


# a deterministic, variance-bearing POSITIVE series — a high per-obs Sharpe the PSR detector can confirm (a
# constant series has zero std ⇒ zero Sharpe by convention, so test inputs must carry realistic dispersion).
def _positive(n: int) -> list[float]:
    return [0.012 + 0.005 * math.sin(i * 1.3) for i in range(n)]   # all in [0.007, 0.017]


def test_edge_half_life_finite_on_decaying_none_on_flat():
    decaying = [0.02 - 0.0019 * i for i in range(11)]  # positive throughout, decaying — a real backtest edge half-life
    hl = edge_half_life(decaying)
    assert hl is not None and hl > 0
    assert edge_half_life([0.01] * 14) is None        # flat ⇒ no finite half-life ⇒ full size


# --- forward confirmation (reuses the live arming gate's PSR floor) -------------------------------------------


def test_forward_confirmation_fires_on_significant_window_only():
    # A strongly, consistently positive window clears the PSR floor; a zero-mean noisy one does not.
    assert is_forward_confirmation(_positive(CONFIRM_MIN_OBS + 4))
    flat_zero = [0.01 if i % 2 else -0.01 for i in range(CONFIRM_MIN_OBS + 4)]
    assert not is_forward_confirmation(flat_zero)
    # too few observations never confirms (fails safe — same as the live gate)
    assert not is_forward_confirmation(_positive(CONFIRM_MIN_OBS - 1))


# --- decay weights: causal, full-at-funding, reset-on-confirmation --------------------------------------------


def test_decay_weights_full_size_at_funding_then_evaporate_without_reconfirmation():
    # a dead forward edge (no confirmation ever) ⇒ the clock only grows ⇒ size decays monotonically after funding
    dead = [-0.001] * 80
    w = decay_weights(dead, tau=20.0)
    assert w[0] == 1.0                                  # just funded ⇒ full size
    assert w[-1] < w[40] < w[10] < 1.0                  # strictly evaporating, no reset
    assert all(0.0 < x <= 1.0 for x in w)


def test_decay_weights_reset_on_forward_confirmation_keeps_size_up():
    # a persistently positive forward edge keeps re-confirming ⇒ the clock keeps resetting ⇒ size stays near full
    w = decay_weights(_positive(80), tau=20.0)
    assert min(w[CONFIRM_MIN_OBS:]) > 0.6               # never collapses while the edge keeps re-proving forward


def test_decay_weights_are_strictly_causal():
    # the weight for period t must depend ONLY on returns[:t]; perturbing the FUTURE cannot move past/present weights
    base = [0.01, 0.008, -0.002, 0.004, -0.01, 0.0, 0.003, -0.006] * 8
    cut = 30
    perturbed = list(base)
    for i in range(cut, len(perturbed)):
        perturbed[i] = -0.05                            # arbitrary future change
    w_base = decay_weights(base, tau=15.0)
    w_pert = decay_weights(perturbed, tau=15.0)
    assert w_base[: cut + 1] == w_pert[: cut + 1]       # weights[0..cut] untouched by returns[cut+1:]


def test_no_decay_when_tau_is_none():
    rets = [0.001 * (i % 5 - 2) for i in range(60)]
    assert decay_weights(rets, tau=None) == [1.0] * len(rets)


# --- hold-until-fail baseline --------------------------------------------------------------------------------


def test_hold_until_fail_is_full_size_until_ruin():
    # default kill_floor=0.0 ⇒ held at full size the whole way (only total ruin pulls it)
    rets = [0.01, -0.02, 0.005, -0.01] * 10
    assert hold_until_fail_weights(rets) == [1.0] * len(rets)
    # a catastrophic drawdown past the kill floor cuts size to zero thereafter
    crash = [0.0, 0.0, -0.6, -0.6, 0.1, 0.1]
    w = hold_until_fail_weights(crash, kill_floor=0.5)
    assert w[:3] == [1.0, 1.0, 1.0] and w[3:] == [0.0, 0.0, 0.0]


def test_decayed_weights_is_overlay_on_hold_until_fail():
    rets = [-0.001] * 60
    huf = hold_until_fail_weights(rets)
    dec = decay_weights(rets, tau=20.0)
    assert decayed_weights(rets, tau=20.0) == [h * d for h, d in zip(huf, dec, strict=True)]


# --- book aggregation: fixed slice, evaporated size sits in cash ----------------------------------------------


def test_book_returns_cash_drag_and_equal_slices():
    a = TrackSeries.from_returns("a", [0.10, 0.10], tau=None)
    b = TrackSeries.from_returns("b", [0.20, -0.20], tau=None)
    # full size on both ⇒ book = mean of the two per period
    full = {"a": [1.0, 1.0], "b": [1.0, 1.0]}
    book = book_returns([a, b], full)
    assert math.isclose(book[0], 0.15) and math.isclose(book[1], -0.05)
    # halve track b's size ⇒ its contribution halves, the freed half earns 0 (cash), not reallocated to a
    half_b = {"a": [1.0, 1.0], "b": [0.5, 0.5]}
    drag = book_returns([a, b], half_b)
    assert math.isclose(drag[0], 0.5 * 0.10 + 0.5 * 0.10) and math.isclose(drag[1], 0.5 * 0.10 + 0.5 * -0.10)


def test_evaluate_book_metrics_are_sane():
    up = _positive(50)
    m = evaluate_book(up, periods_per_year=365)
    assert m.n == 50 and m.total_return > 0 and m.max_drawdown == 0.0
    assert m.sharpe > 0 and math.isinf(m.calmar)        # no drawdown + up ⇒ infinite Calmar


# --- the method-validation verdict on the synthetic panel -----------------------------------------------------


def test_decay_wins_when_the_edge_decays_past_zero():
    panel = synthetic_panel(n_tracks=12, periods=160, seed=7, mode="decaying", funded_at=50)
    rep = run_study(panel, data_source="synthetic-fixture")
    assert rep.decayed_wins and rep.verdict == "DECAYED-WINS"
    assert rep.decayed.sharpe > rep.hold_until_fail.sharpe
    assert rep.decayed.max_drawdown < rep.hold_until_fail.max_drawdown   # and it cuts the drawdown too


def test_persistent_edge_is_a_tie_overlay_stays_out_of_the_way():
    panel = synthetic_panel(n_tracks=12, periods=160, seed=7, mode="persistent", funded_at=50)
    rep = run_study(panel, data_source="synthetic-fixture")
    assert not rep.decayed_wins                          # no decay ⇒ evaporation must not manufacture a win
    assert abs(rep.sharpe_margin) < 0.5                  # decayed ≈ hold (only a tiny cash-drag cost)


def test_reconfirmed_edge_is_not_over_pulled():
    panel = synthetic_panel(n_tracks=12, periods=160, seed=7, mode="reconfirmed", funded_at=50, reconfirm_every=37)
    rep = run_study(panel, data_source="synthetic-fixture")
    # a genuinely re-confirmed edge keeps its size: the overlay does NOT badly underperform hold-until-fail
    assert rep.sharpe_margin > -0.5


def test_run_study_is_deterministic():
    a = run_study(synthetic_panel(n_tracks=8, periods=120, seed=3, mode="decaying"), data_source="x")
    b = run_study(synthetic_panel(n_tracks=8, periods=120, seed=3, mode="decaying"), data_source="x")
    assert a.headline == b.headline and a.sharpe_margin == b.sharpe_margin


# --- the portfolio_snapshots loader (real driver) -------------------------------------------------------------


def _snap(store: Store, ref_id: str, equity: str) -> None:
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": ref_id, "ts": utcnow(), "equity": equity,
         "cash": "0", "positions_value": equity, "pnl": "0", "drawdown": "0"},
    )


def test_load_tracks_from_store_reads_snapshots_and_is_empty_on_fresh_db(tmp_path):
    store = _store(tmp_path)
    assert load_tracks_from_store(store) == []          # fresh DB ⇒ honest-empty, never an error
    equity = 1000.0
    for _ in range(30):
        equity *= 1.0 + 0.002
        _snap(store, "v:BTCUSDT:binance", f"{equity:.4f}")
    tracks = load_tracks_from_store(store, discovery_frac=0.25)
    assert len(tracks) == 1
    tr = tracks[0]
    assert tr.track_id == "v:BTCUSDT:binance"
    assert len(tr.returns) >= 2 and all(math.isfinite(r) for r in tr.returns)


# --- the design-only live multiplier --------------------------------------------------------------------------


def test_live_decay_multiplier_is_the_last_decay_weight():
    rets = [-0.001] * 60
    assert live_decay_multiplier(rets, tau=20.0) == decay_weights(rets, tau=20.0)[-1]
    assert live_decay_multiplier([], tau=20.0) == 1.0   # no history ⇒ full size
    assert live_decay_multiplier(rets, tau=None) == 1.0  # no decay ⇒ full size


def test_forward_dsr_floor_constant_matches_the_live_gate():
    # the instrument borrows the SAME forward-significance floor the live arming gate uses — not a new magic number
    from cosmu.research import decay_monitor as DM

    assert DM.CONFIRM_MIN_FORWARD_DSR == PAPER_MIN_FORWARD_DSR
