# intent: the experiments registry package — a runs/experiments ledger so every finder/gate run logs its exact
# config + seed + data_version + metrics (COMPARABLE across runs, EXACTLY REGENERABLE) plus a continuous
# forward-P&L SOFT-LABEL that gives the ML ranker a gradient before any gate-pass exists. Public surface only;
# implementations live in registry.py (the ledger + hook), data_version.py (the input-data fingerprint), and
# soft_labels.py (the soft-label → ranker bridge).

from __future__ import annotations

from cosmu.experiments.data_version import (
    EMPTY_DATA_VERSION,
    data_version,
    fingerprint,
)
from cosmu.experiments.registry import (
    KIND_ABLATION,
    KIND_CROSS_ASSET,
    KIND_EDGE_GATE,
    KIND_FINDER,
    KIND_FINDER_REFINE,
    ExperimentRecord,
    count_experiments,
    log_experiment,
    log_experiments,
    recent_experiments,
)
from cosmu.experiments.soft_labels import (
    SoftLabeledOutcome,
    soft_label_training_set,
    soft_labeled_outcomes,
)

__all__ = [
    "EMPTY_DATA_VERSION",
    "ExperimentRecord",
    "KIND_ABLATION",
    "KIND_CROSS_ASSET",
    "KIND_EDGE_GATE",
    "KIND_FINDER",
    "KIND_FINDER_REFINE",
    "SoftLabeledOutcome",
    "count_experiments",
    "data_version",
    "fingerprint",
    "log_experiment",
    "log_experiments",
    "recent_experiments",
    "soft_label_training_set",
    "soft_labeled_outcomes",
]
