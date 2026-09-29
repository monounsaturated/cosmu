# intent: SOFT-LABELS — turn the experiments registry's continuous forward-P&L into a training signal the ML
# survival ranker can learn from BEFORE any candidate has passed the deterministic gate. The binary survival
# label (passed-gate vs killed) is single-class during cold-start (nothing has passed yet), so a classifier
# can't train; the soft label (net forward P&L per variant) is continuous and always present, giving the ranker
# a real gradient. inputs: a Store (reads the `experiments` rows that carry a soft_label + a reconstructable
# metrics dump); outputs: a (feature_vector, label) training set in survival.py's OWN feature vocabulary.
# invariants: ORDERING ONLY — this feeds the ranker, never the scorer/gate (the deterministic gate stays the
# sole survival authority); point-in-time (reads only already-logged past runs); composes survival.py's
# FEATURE_NAMES + features_from_metrics rather than duplicating them; offline + deterministic.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics
from cosmu.ml.survival import SurvivalFeatures, features_from_metrics


@dataclass(frozen=True)
class SoftLabeledOutcome:
    """One past run as a soft-labeled training row: its screen features + the continuous forward-P&L it earned.
    `forward_pnl` is net of costs (the finder logs `net_profit`); `features` is in the survival vocabulary."""

    label: str
    forward_pnl: float
    features: SurvivalFeatures


def _metrics_from(row_metrics: Any) -> BacktestMetrics | None:
    """Reconstruct a BacktestMetrics from a logged metrics dump, or None if the row carried a verdict-shaped
    payload (gate runs) rather than a full metrics dump (finder variants). Tolerant — never raises."""
    if not isinstance(row_metrics, dict):
        return None
    try:
        return BacktestMetrics(**row_metrics)
    except Exception:  # noqa: BLE001 — not a metrics dump (e.g. a gate verdict) → skip this row
        return None


def soft_labeled_outcomes(store: Store) -> list[SoftLabeledOutcome]:
    """Every logged experiment that carries BOTH a continuous forward-P&L soft_label AND a reconstructable
    metrics dump, projected onto the survival feature vocabulary. Oldest-first (point-in-time order) so a
    downstream chronological split never trains on the future. Reads the registry only — no gate, no money."""
    from cosmu.experiments.registry import recent_experiments

    rows = recent_experiments(store, limit=100_000)
    rows.reverse()  # recent_experiments is newest-first; soft-label training wants oldest-first
    out: list[SoftLabeledOutcome] = []
    for r in rows:
        soft = r.get("soft_label")
        if soft is None:
            continue
        metrics = _metrics_from(r.get("metrics"))
        if metrics is None:
            continue
        out.append(
            SoftLabeledOutcome(
                label=str(r.get("label") or r.get("id")),
                forward_pnl=float(soft),
                features=features_from_metrics(metrics),
            )
        )
    return out


def soft_label_training_set(store: Store) -> tuple[list[list[float]], list[int]]:
    """The (feature_vectors, labels) the survival model trains on during cold-start. The label is the SIGN of
    the net forward P&L — 1 if the variant made money out-of-sample, 0 if it lost — a legitimate, always-present
    target that shapes the ranker toward profitable feature regions before any gate-pass exists. Returns the
    SAME (vectors, labels) contract as survival._labeled_outcomes so the model's training path is unchanged;
    only the LABEL SOURCE differs (forward-P&L sign instead of the not-yet-existent gate verdict)."""
    outcomes = soft_labeled_outcomes(store)
    vectors = [o.features.vector() for o in outcomes]
    labels = [1 if o.forward_pnl > 0.0 else 0 for o in outcomes]
    return vectors, labels
