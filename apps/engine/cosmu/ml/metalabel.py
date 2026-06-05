# intent: the runtime for triple-barrier META-LABELING — a SECONDARY regularized-logistic gate that the backtest
# consults at each primary entry to SIZE or SKIP the trade (never flip its direction). It (1) labels each past
# primary-signal event by which of the three barriers (stop / take-profit / time) it hit first, netted of cost
# (win=1 else 0) and (2) trains an EXPANDING-WINDOW point-in-time logistic on the resolved events to predict the
# current event's win probability. inputs: precomputed primary-signal events with PIT feature vectors + the bar
# path; outputs: a take/size decision per entry. invariants: point-in-time (a decision at bar idx only trains on
# events whose barrier resolved on a STRICTLY earlier bar — never its own outcome), deterministic (fixed-seed
# logistic, fixed iteration order), offline (pure-Python, zero deps), size/skip ONLY (direction is untouched).

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.ml.logistic import apply_standardization, sigmoid, standardize, train_logistic

# How many RESOLVED primary events must exist before the secondary model trains and the gate activates. Below
# this the trade is ungated (the bare primary book) — a thin/single-class early model never gets to veto. Mirrors
# the survival ranker's MIN_TRAIN_LABELS: a statistical floor, not a strategy knob.
META_MIN_TRAIN = 30
# Ridge penalty on the secondary logistic (same default as the survival head). A small constant: spot's design
# matrix is thin and correlated, so some shrinkage keeps the weights from chasing noise.
META_L2 = 1e-3
# Gradient-descent epochs for the secondary logistic. Lower than the survival head (400): the gate retrains many
# times across a backtest, and the standardized thin design converges fast — this bounds the per-run cost.
META_EPOCHS = 200
# Refit cadence: re-fit the logistic only once the resolved-event training set has grown by this many events
# since the last fit (deterministic — the count grows monotonically with the bar index). Bounds total refits to
# O(events / cadence) per symbol instead of one fit per entry, with negligible drift between refits.
META_REFIT_EVERY = 20


@dataclass(frozen=True)
class MetaEvent:
    """One labeled primary-signal event. `signal_idx` is the fill bar (the signal fired on bar signal_idx-1);
    `resolve_idx` is the bar on which the triple barrier was hit (the outcome becomes known); `features` is the
    point-in-time feature vector read at the signal bar; `label` is 1 if the barrier outcome was a net winner."""

    signal_idx: int
    resolve_idx: int
    features: list[float]
    label: int


def triple_barrier_outcome(
    entry_idx: int,
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    stop_pct: float,
    take_pct: float,
    max_hold_bars: int,
    d: int,
    roundtrip_cost: float,
) -> tuple[int, int]:
    """Label one primary event by the FIRST of the three barriers it hits, walking the path from the bar after
    entry. Reference price is the close at the signal/fill bar `entry_idx`. The stop sits the adverse side of
    entry (below for a long, above for a short), the take-profit the favourable side, and the time barrier is
    `max_hold_bars` later. Stop is checked first each bar (worst-case priority, matching the live exit order).
    The label is 1 iff the realized barrier return, netted of `roundtrip_cost`, is positive. Returns
    (label, resolve_idx). Side-aware via `d` (+1 long / -1 short) so a short's barriers mirror a long's.

    Point-in-time: the walk only ever reads bars at/after entry, and the caller only TRAINS on events whose
    `resolve_idx` is strictly before the decision bar — so a label never encodes information from the future of
    the bar at which it is used."""
    entry_ref = closes[entry_idx]
    if entry_ref <= 0:
        return 0, entry_idx
    stop = entry_ref * (1 - d * stop_pct)
    tp = entry_ref * (1 + d * take_pct)
    last = min(len(closes) - 1, entry_idx + max(1, max_hold_bars))
    for k in range(entry_idx + 1, last + 1):
        adverse = lows[k] if d == 1 else highs[k]
        favourable = highs[k] if d == 1 else lows[k]
        # Stop first (worst-case priority): long stops when the low breaches the stop, a short when the high does.
        stop_hit = adverse <= stop if d == 1 else adverse >= stop
        if stop_hit:
            ret = d * (stop / entry_ref - 1.0) - roundtrip_cost
            return (1 if ret > 0 else 0), k
        tp_hit = favourable >= tp if d == 1 else favourable <= tp
        if tp_hit:
            ret = d * (tp / entry_ref - 1.0) - roundtrip_cost
            return (1 if ret > 0 else 0), k
    # Time barrier: close out at the last in-window bar's close.
    ret = d * (closes[last] / entry_ref - 1.0) - roundtrip_cost
    return (1 if ret > 0 else 0), last


@dataclass
class MetaGate:
    """The secondary-model gate over a single symbol's primary events. Holds every labeled `MetaEvent` and, at
    each live entry, trains an expanding-window logistic on the events RESOLVED before the decision bar to score
    the current event. Caches the fit and only refits once the training set has grown by `META_REFIT_EVERY`, so
    a backtest does O(events / cadence) fits rather than one per entry. Pure decision object: it never mutates
    bars or positions — it returns (take, size_multiplier) and the backtest does the rest."""

    events: list[MetaEvent]
    min_train: int = META_MIN_TRAIN
    l2: float = META_L2
    epochs: int = META_EPOCHS
    refit_every: int = META_REFIT_EVERY
    # Cached fit: (means, stds, weights, bias, n_events_at_fit). None until the first activation.
    _model: tuple[list[float], list[float], list[float], float, int] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Sorted by resolve_idx so "events resolved before bar idx" is a cheap prefix — and deterministic.
        self.events = sorted(self.events, key=lambda e: e.resolve_idx)

    def _resolved_before(self, idx: int) -> list[MetaEvent]:
        out: list[MetaEvent] = []
        for e in self.events:
            if e.resolve_idx >= idx:
                break
            out.append(e)
        return out

    def _fit(self, train: list[MetaEvent]) -> tuple[list[float], list[float], list[float], float, int]:
        rows = [e.features for e in train]
        labels = [e.label for e in train]
        means, stds = standardize(rows)
        std_rows = [apply_standardization(r, means, stds) for r in rows]
        w, b = train_logistic(std_rows, labels, epochs=self.epochs, l2=self.l2)
        return means, stds, w, b, len(train)

    def decide(self, idx: int, featvec: list[float] | None, threshold: float, proportional: bool) -> tuple[bool, float]:
        """Decide whether to take the primary trade firing at bar `idx`, and at what size multiplier.

        Returns (take, size_multiplier). The gate stays OUT of the way — returning (True, 1.0), the unchanged
        primary trade — whenever it cannot honestly score: a missing/incomplete feature vector, fewer than
        `min_train` resolved events, or a single-class training set (no win/loss contrast to learn). Once it can
        score, it trains (or reuses the cached fit), predicts the win probability p, and SKIPS below `threshold`;
        at/above it the trade is taken at full size, or sized by p when `proportional`. Only ever sizes/skips."""
        if featvec is None:
            return True, 1.0
        train = self._resolved_before(idx)
        if len(train) < self.min_train:
            return True, 1.0
        labels = [e.label for e in train]
        if len(set(labels)) < 2:
            return True, 1.0
        if self._model is None or len(train) >= self._model[4] + self.refit_every:
            self._model = self._fit(train)
        means, stds, w, b, _ = self._model
        x = apply_standardization(featvec, means, stds)
        p = sigmoid(b + sum(w[j] * x[j] for j in range(len(x))))
        if p < threshold:
            return False, 0.0
        return True, (p if proportional else 1.0)
