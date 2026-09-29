# Tests for the META-LABEL MODEL (cosmu/ml/meta_label.py): the propose-only secondary classifier that consumes
# the experiments registry's forward-P&L SOFT-LABELS and turns them into a take/skip filter over a primary
# model's signals. Proves (1) it re-exports the canonical triple-barrier labeler (same outcome as the in-backtest
# gate's), (2) cold-start always-takes so the filter can only ever SUBTRACT signals, never add/flip one,
# (3) trained on a separable soft-label corpus it SKIPS low-probability signals and PASSES high-probability ones,
# (4) a missing feature row is ungated, and (5) it composes with the soft-labels (the SAME corpus the survival
# ranker trains on drives the filter) and is deterministic (same store → byte-identical model). Fully offline +
# deterministic — no network, no fixtures.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.experiments import KIND_FINDER, ExperimentRecord, log_experiments
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics
from cosmu.ml.meta_label import (
    MetaLabelModel,
    load_meta_label_model,
    triple_barrier_outcome,
)
from cosmu.ml.survival import features_from_metrics

# --------------------------------------------------------------------------- re-exported triple-barrier labeler


def _flat(prices: list[float]) -> tuple[list[float], list[float], list[float]]:
    """highs == lows == closes so the barrier walk lands exactly on the path (no intrabar ambiguity)."""
    return list(prices), list(prices), list(prices)


def test_reexported_triple_barrier_take_profit_first_is_a_win():
    # The module re-exports the canonical labeler (single source of truth in cosmu.ml.metalabel). A straight rise
    # hits the take-profit before any stop/time barrier → a net winner. Known synthetic path, known outcome.
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.05, take_pct=0.10, max_hold_bars=10, d=1, roundtrip_cost=0.002
    )
    assert label == 1
    assert resolve == 3  # tp carries a float epsilon so 110.0 just misses; the fill lands at 115


def test_reexported_triple_barrier_stop_first_is_a_loss():
    # A straight drop hits the stop before the (unreachable) take-profit → a net loser.
    closes = [100.0, 97.0, 94.0, 90.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.05, take_pct=0.20, max_hold_bars=10, d=1, roundtrip_cost=0.002
    )
    assert label == 0
    assert resolve == 2  # 97 > 95 at index 1; the 94 <= 95 stop fires at index 2


# --------------------------------------------------------------------------- the soft-label model


def _store(tmp_path, name: str = "meta") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _metrics(sharpe_per_obs: float, oos: float, trades: int = 40) -> BacktestMetrics:
    return BacktestMetrics(
        oos_return=Decimal(str(oos)),
        sharpe=Decimal(str(sharpe_per_obs * 16)),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0.05"),
        win_rate=Decimal("0.5"),
        num_trades=trades,
        sharpe_per_obs=Decimal(str(sharpe_per_obs)),
        n_obs=200,
        folds_positive_pct=Decimal("0.6"),
    )


def _seed_soft_corpus(store: Store, n: int = 40) -> None:
    """Log n finder experiments with a SEPARABLE soft-label corpus: winners carry a positive sharpe_per_obs and a
    positive forward-P&L, losers the mirror. This is the cross-run corpus the survival ranker ALSO trains on —
    here it drives the meta-label filter. No gate-pass (gate_passed=False) → exactly the cold-start state where
    only the soft-label gradient exists."""
    recs = []
    for i in range(n):
        win = i % 2 == 0
        sharpe = 0.04 if win else -0.04
        pnl = (0.02 + i * 0.001) if win else -(0.02 + i * 0.001)
        recs.append(
            ExperimentRecord(
                kind=KIND_FINDER,
                source="finder",
                label=f"v{i}",
                config={"config_tag": f"v{i}"},
                metrics=_metrics(sharpe, pnl).model_dump(mode="json"),
                seed=7,
                data_version="data:fixed",
                soft_label=pnl,
                gate_passed=False,
            )
        )
    log_experiments(store, recs)


def _winner_features() -> list[float]:
    """A primary signal whose screen metrics look like the corpus's WINNERS (positive per-obs Sharpe)."""
    return features_from_metrics(_metrics(0.04, 0.05)).vector()


def _loser_features() -> list[float]:
    """A primary signal whose screen metrics look like the corpus's LOSERS (negative per-obs Sharpe)."""
    return features_from_metrics(_metrics(-0.04, -0.05)).vector()


def test_cold_start_filter_always_takes(tmp_path):
    # Below the training floor (and with no corpus at all) the model is untrained → the filter always-takes at a
    # neutral 0.5, so it can only ever SUBTRACT primary signals once it has learned, never veto from ignorance.
    store = _store(tmp_path, "cold")
    _seed_soft_corpus(store, 10)  # < META_LABEL_MIN_TRAIN (30)
    model = load_meta_label_model(store)
    assert model.trained is False
    d = model.filter_signal(_loser_features(), threshold=0.99)
    assert d.take is True and d.win_probability == 0.5 and d.trained is False


def test_trained_filter_skips_low_passes_high(tmp_path):
    # On a separable soft-label corpus the trained filter scores a winner-shaped signal high and a loser-shaped
    # signal low: a mid threshold PASSES the winner and SKIPS the loser. This is the propose-only edge.
    store = _store(tmp_path, "trained")
    _seed_soft_corpus(store, 40)
    model = load_meta_label_model(store)
    assert model.trained is True
    assert model.backend == "logistic_soft"
    assert model.n_labels == 40

    win = model.filter_signal(_winner_features(), threshold=0.5)
    lose = model.filter_signal(_loser_features(), threshold=0.5)
    assert win.take is True and win.win_probability > 0.5
    assert lose.take is False and lose.win_probability < 0.5
    # an impossible-to-clear threshold skips even the winner — the filter only ever subtracts, never adds.
    assert model.filter_signal(_winner_features(), threshold=1.01).take is False


def test_missing_feature_row_is_ungated(tmp_path):
    # No feature row to score → the filter stays out of the way (take, neutral 0.5), even when trained.
    store = _store(tmp_path, "missing")
    _seed_soft_corpus(store, 40)
    model = load_meta_label_model(store)
    assert model.trained is True
    d = model.filter_signal(None, threshold=0.99)
    assert d.take is True and d.win_probability == 0.5


def test_single_class_corpus_stays_untrained(tmp_path):
    # Enough rows but only WINNERS (no contrast to learn) → untrained, always-take. The filter never vetoes off a
    # one-sided corpus, mirroring the survival ranker's single-class guard.
    store = _store(tmp_path, "oneclass")
    recs = [
        ExperimentRecord(
            kind=KIND_FINDER,
            source="finder",
            label=f"w{i}",
            config={"config_tag": f"w{i}"},
            metrics=_metrics(0.04, 0.02 + i * 0.001).model_dump(mode="json"),
            seed=7,
            data_version="data:fixed",
            soft_label=0.02 + i * 0.001,  # all winners
            gate_passed=False,
        )
        for i in range(40)
    ]
    log_experiments(store, recs)
    model = load_meta_label_model(store)
    assert model.trained is False
    assert model.filter_signal(_loser_features(), threshold=0.99).take is True


def test_model_is_deterministic(tmp_path):
    # Same soft-label corpus → byte-identical model (fixed-seed pure-Python logistic, fixed iteration order), so
    # the propose-only verdicts are reproducible across runs.
    store = _store(tmp_path, "det")
    _seed_soft_corpus(store, 40)
    a = load_meta_label_model(store)
    b = load_meta_label_model(store)
    assert isinstance(a, MetaLabelModel)
    assert (a._weights, a._bias, a._means, a._stds) == (b._weights, b._bias, b._means, b._stds)
    feat = _winner_features()
    assert a.win_probability(feat) == b.win_probability(feat)
