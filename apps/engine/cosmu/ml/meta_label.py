# intent: the META-LABEL MODEL interface — a SECONDARY, PROPOSE-ONLY classifier that consumes the experiments
# registry's continuous forward-P&L SOFT-LABELS (the same cross-run corpus the survival ranker learns from) and
# turns them into a take/skip filter over a PRIMARY model's signals. It answers one question Lopez de Prado's
# meta-labeling poses: given that the primary model fired, what is the probability this trade is a NET winner —
# and should we act on it? inputs: a Store (reads already-logged past runs' soft-labels) for training, plus a
# per-signal feature row at serve time; outputs: a (take, win_probability) decision. invariants: PROPOSE-ONLY
# (a training artifact / advisory object — NEVER wired into the live money path; the deterministic gate and the
# backtest's own in-path MetaGate stay the sole authorities); point-in-time (trains only on already-resolved
# past outcomes, oldest-first, via soft_labeled_outcomes); deterministic (fixed-seed pure-Python logistic, fixed
# iteration order); offline (zero required dependency); FILTER-ONLY (it can skip a primary signal or pass it
# through — it never flips direction or manufactures a trade). It COMPOSES rather than duplicates: the canonical
# triple-barrier labeler + in-backtest gate live in cosmu.ml.metalabel and are re-exported here; the soft-label
# corpus + survival feature vocabulary live in cosmu.experiments.soft_labels / cosmu.ml.survival.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.knowledge.store import Store
from cosmu.ml.logistic import apply_standardization, sigmoid, standardize, train_logistic

# The canonical triple-barrier labeler + in-backtest secondary gate are re-exported (single source of truth in
# cosmu.ml.metalabel — this module is the cross-run sibling that learns from the persisted soft-label corpus, not
# from a single backtest's path). Importing them here gives `cosmu.ml.meta_label` one coherent meta-labeling
# surface without copying a line of barrier logic.
from cosmu.ml.metalabel import MetaEvent, MetaGate, triple_barrier_outcome

__all__ = [
    "MetaEvent",
    "MetaGate",
    "MetaLabelDecision",
    "MetaLabelModel",
    "load_meta_label_model",
    "triple_barrier_outcome",
]

# How many soft-labeled past outcomes must exist before the model trains and the filter activates. Below this the
# filter stays OUT of the way (always-take) — a thin/single-class early model never gets to veto a primary signal.
# Mirrors the survival ranker's MIN_TRAIN_LABELS and the in-backtest gate's META_MIN_TRAIN: a statistical floor,
# not a strategy knob.
META_LABEL_MIN_TRAIN = 30
# Ridge penalty on the secondary logistic (same default as the survival head and the in-backtest gate). The
# soft-label design matrix is thin and correlated, so some shrinkage keeps the weights from chasing noise.
META_LABEL_L2 = 1e-3
# Gradient-descent epochs for the secondary logistic. Matches the in-backtest gate (META_EPOCHS): the standardized
# thin design converges fast and this bounds the one-shot training cost.
META_LABEL_EPOCHS = 200
# Default win-probability cut: act on a primary signal only when the model judges it more-likely-than-not a net
# winner. A neutral 0.5 — callers pass their own fitted threshold; this is only the propose-only default.
META_LABEL_DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class MetaLabelDecision:
    """One propose-only verdict on a primary signal. `take` is whether the secondary model would act on it;
    `win_probability` is the model's P(net winner) in [0,1]; `trained` says whether a trained model produced the
    probability or the cold-start always-take fallback did (so a caller can tell a real veto from an inactive
    filter). Advisory only — nothing here moves money."""

    take: bool
    win_probability: float
    trained: bool


@dataclass
class MetaLabelModel:
    """The secondary meta-label classifier over the soft-label corpus. Construct via `load_meta_label_model(store)`
    so it trains on the registry's already-logged forward-P&L outcomes (oldest-first, point-in-time). The public
    surface is `filter_signal(...)` — given a primary signal's feature row (in the survival feature vocabulary),
    return a propose-only take/skip + win-probability. Cold-start (untrained) ALWAYS takes, so the filter can only
    ever SUBTRACT primary signals once it has learned — never add or flip one. A pure decision object: it owns no
    bars, no positions, no money path."""

    trained: bool = False
    n_labels: int = 0
    backend: str = "heuristic"  # "logistic_soft" once trained on the soft-label corpus, else "heuristic"
    _means: list[float] | None = None
    _stds: list[float] | None = None
    _weights: list[float] | None = None
    _bias: float = 0.0

    def win_probability(self, features: list[float]) -> float:
        """P(this primary signal is a net winner) in [0,1] for one feature row. Falls back to a neutral 0.5 when
        untrained (cold-start), so the interface is identical in both regimes — a caller never branches on it."""
        if not self.trained:
            return 0.5
        assert self._means is not None and self._stds is not None and self._weights is not None
        x = apply_standardization(features, self._means, self._stds)
        return sigmoid(self._bias + sum(self._weights[j] * x[j] for j in range(len(x))))

    def filter_signal(
        self, features: list[float] | None, *, threshold: float = META_LABEL_DEFAULT_THRESHOLD
    ) -> MetaLabelDecision:
        """Propose-only verdict on a PRIMARY signal whose feature row is `features` (survival vocabulary order).

        The filter stays OUT of the way — returning take=True at the neutral 0.5 — whenever it cannot honestly
        score: a missing feature row, or an untrained (cold-start) model. Once trained it predicts the win
        probability p and SKIPS below `threshold`, otherwise passes the signal through. It only ever subtracts:
        it cannot turn a non-signal into a trade, nor flip a long into a short — and it never touches money."""
        if features is None or not self.trained:
            return MetaLabelDecision(take=True, win_probability=0.5, trained=self.trained)
        p = self.win_probability(features)
        return MetaLabelDecision(take=p >= threshold, win_probability=p, trained=True)


def load_meta_label_model(store: Store, *, min_train: int = META_LABEL_MIN_TRAIN) -> MetaLabelModel:
    """Build the meta-label model from the experiments registry's SOFT-LABELS. Reuses
    `soft_label_training_set` — the SAME oldest-first (feature_vectors, labels) the survival ranker trains on,
    where the label is the SIGN of net forward P&L (1 == made money out-of-sample). Below `min_train` resolved
    soft-labels, or a single-class corpus, returns an untrained model whose filter always-takes (no veto from a
    model that cannot learn). Past the threshold it trains a deterministic pure-Python ridge logistic and the
    filter activates. PROPOSE-ONLY: this returns a training artifact / advisory object — it is never on the gate
    or money path, where the deterministic gate (master/scorer.py) stays the sole survival authority."""
    from cosmu.experiments.soft_labels import soft_label_training_set

    rows, labels = soft_label_training_set(store)
    n = len(rows)
    if n < min_train or len(set(labels)) < 2:
        return MetaLabelModel(trained=False, n_labels=n, backend="heuristic")

    means, stds = standardize(rows)
    std_rows = [apply_standardization(r, means, stds) for r in rows]
    w, b = train_logistic(std_rows, labels, epochs=META_LABEL_EPOCHS, l2=META_LABEL_L2)
    return MetaLabelModel(
        trained=True,
        n_labels=n,
        backend="logistic_soft",
        _means=means,
        _stds=stds,
        _weights=w,
        _bias=b,
    )
