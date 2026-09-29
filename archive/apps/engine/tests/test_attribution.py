# Offline tests for SIM→live variance attribution (research/attribution.py). PURE + deterministic + REVIEW-ONLY:
# it only EXPLAINS a track's sim/live divergence into fees · slippage · funding · signal-decay · regime (+ an
# honest residual) — it never funds, defunds, or moves money. Covers the additive decomposition + sign
# conventions, the Brinson regime-allocation effect, the alpha-decay reuse of master/drift, and the store reader
# over the executions + portfolio_snapshots ledgers.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.research.attribution import (
    CostLeg,
    RegimeBucket,
    attribute_track,
    attribute_variance,
    decay_contribution,
    regime_contribution,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/attr.sqlite3", openrouter_api_key=None))


# --- pure decomposition ---------------------------------------------------------------------------


def test_components_plus_residual_reconstruct_the_divergence_exactly():
    attr = attribute_variance(
        "s1",
        sim_net=0.010,
        live_net=0.004,
        fees=CostLeg(0.0005, 0.0009),       # paying more fees live → negative contribution
        slippage=CostLeg(0.0003, 0.0011),   # worse slippage live → negative contribution
        funding=CostLeg(0.0, 0.0),
        signal_decay=-0.0020,
        regime=-0.0010,
        n_live=12,
    )
    # explained + residual must sum to the divergence to machine precision (additive by construction).
    assert abs((attr.explained + attr.residual) - attr.divergence) < 1e-12
    assert abs(attr.divergence - (0.004 - 0.010)) < 1e-12


def test_cost_legs_have_the_right_sign():
    # Higher fees/slippage live than sim drags the divergence DOWN; funding received live pushes it UP.
    attr = attribute_variance(
        "s2", sim_net=0.0, live_net=0.0,
        fees=CostLeg(0.0002, 0.0007), slippage=CostLeg(0.0001, 0.0004),
        funding=CostLeg(-0.0001, 0.0003),
    )
    by = {c.name: c.contribution for c in attr.components}
    assert by["fees"] < 0          # 0.0002 - 0.0007
    assert by["slippage"] < 0      # 0.0001 - 0.0004
    assert by["funding"] > 0       # 0.0003 - (-0.0001)


def test_regime_allocation_effect_is_brinson():
    # Live spent 80% in 'bull' (sim only 40%); bull paid +2% gross in sim, chop −1%. Allocation effect is the
    # weight shift dotted with the sim gross: (0.8-0.4)*0.02 + (0.2-0.6)*(-0.01) = 0.008 + 0.004 = 0.012.
    buckets = [
        RegimeBucket("bull", sim_weight=0.4, live_weight=0.8, sim_gross=0.02),
        RegimeBucket("chop", sim_weight=0.6, live_weight=0.2, sim_gross=-0.01),
    ]
    effect, note = regime_contribution(buckets)
    assert abs(effect - 0.012) < 1e-12
    assert "bull" in note


def test_regime_effect_empty_folds_into_residual():
    effect, note = regime_contribution([])
    assert effect == 0.0
    assert "residual" in note


def test_signal_decay_reuses_drift_and_is_negative_when_edge_erodes():
    # An edge that declines from strong to barely-positive: current fitted edge sits BELOW the funded reference,
    # so the decay contribution is negative (the usual live shortfall). Reuses master/drift's edge-decay fit.
    decaying = [0.02 - 0.0019 * i for i in range(11)]
    reference = sum(decaying[:5]) / 5  # funded baseline
    contribution, note = decay_contribution(decaying, reference)
    assert contribution < 0
    assert "edge" in note


def test_signal_decay_insufficient_history_is_zero():
    contribution, note = decay_contribution([0.01, 0.02], 0.01)
    assert contribution == 0.0
    assert "insufficient" in note


def test_headline_names_the_direction_and_top_drivers():
    attr = attribute_variance(
        "s3", sim_net=0.01, live_net=0.002,
        slippage=CostLeg(0.0, 0.005), signal_decay=-0.003, n_live=10,
    )
    head = attr.headline()
    assert "live BELOW sim" in head
    assert "slippage" in head  # the largest-magnitude driver surfaces


# --- store reader ---------------------------------------------------------------------------------


def _snap(store: Store, ref_id: str, equity: str) -> None:
    store.insert(
        "portfolio_snapshots",
        {"scope": "track", "ref_id": ref_id, "ts": utcnow(), "equity": equity, "cash": "0",
         "positions_value": equity, "pnl": "0", "drawdown": "0"},
    )


def _exec(store: Store, vid: str, *, fee: str, slippage: str, is_paper: int) -> None:
    run_id = store.insert("runs", {"mode": "sim", "seed": 1, "started_at": utcnow(), "status": "done"})
    store.insert(
        "executions",
        {"run_id": run_id, "strategy_version_id": vid, "instrument_id": "binance:BTCUSDT", "venue_id": "binance",
         "side": "buy", "qty": "1", "price": "100", "fee": fee, "slippage": slippage,
         "order_type": "market", "is_paper": is_paper, "ts": utcnow(), "fill_log": "{}"},
    )


def test_attribute_track_reads_real_rows_and_finds_live_cost_drift(tmp_path):
    store = _store(tmp_path)
    vid = "vX"
    # A track whose marked value rises then flattens (edge eroding), still nominally positive.
    for eq in ("1000", "1020", "1038", "1050", "1057", "1060", "1062", "1063"):
        _snap(store, vid, eq)
    # Sim fills are cheap (modeled); live fills pay materially more fee + slippage (real execution is worse).
    _exec(store, vid, fee="0.05", slippage="0.0003", is_paper=1)   # sim: 5 bps fee on notional 100
    _exec(store, vid, fee="0.12", slippage="0.0015", is_paper=0)   # live: 12 bps fee, worse slippage

    attr = attribute_track(store, vid)
    by = {c.name: c.contribution for c in attr.components}
    assert attr.n_live == 7
    assert by["fees"] < 0       # live paid more fee per trade than sim
    assert by["slippage"] < 0   # live slippage worse than sim
    # The decomposition stays additive over real data too.
    assert abs((attr.explained + attr.residual) - attr.divergence) < 1e-12


def test_attribute_track_explicit_sim_edge_is_labelled_backtest(tmp_path):
    store = _store(tmp_path)
    vid = "vY"
    for eq in ("1000", "1005", "1009", "1012", "1014"):
        _snap(store, vid, eq)
    attr = attribute_track(store, vid, sim_edge=0.02)
    assert attr.sim_reference == "backtest"
    assert abs(attr.sim_net - 0.02) < 1e-12


def test_attribute_track_marks_money_path_untouched(tmp_path):
    # The reader is read-only: profiling a funded track writes NO money-path rows (no executions/positions added).
    store = _store(tmp_path)
    pf = Portfolio(store)
    pf.apply_fill(instrument_id="binance:BTCUSDT", symbol="BTCUSDT", venue="binance", side=1,
                  qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="vZ")
    pf.mark_to_market({"binance:BTCUSDT": Decimal("100")})
    pf.mark_to_market({"binance:BTCUSDT": Decimal("110")})
    before = store.row("SELECT COUNT(*) AS n FROM executions")["n"]
    attribute_track(store, "vZ")
    after = store.row("SELECT COUNT(*) AS n FROM executions")["n"]
    assert before == after  # attribution is pure review — it moved nothing
