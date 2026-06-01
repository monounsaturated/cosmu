# intent: the ML phase — a deterministic regime classifier the model later refines, and a tabular SURVIVAL
# model that only ORDERS the validation queue (prioritizes compute) and never vetoes an idea. The scorer/gate
# stay out of this package entirely. Everything is offline with NO extra dependency: XGBoost/LightGBM are
# optional and a pure-Python deterministic fallback keeps CI green with no lib installed.

from __future__ import annotations

from cosmu.ml.regime import (
    Regime,
    current_regime,
    proven_regimes,
    regime_eligible,
)
from cosmu.ml.survival import (
    SurvivalFeatures,
    SurvivalModel,
    SurvivalRanking,
    features_from_metrics,
    load_survival_model,
)

__all__ = [
    "Regime",
    "current_regime",
    "proven_regimes",
    "regime_eligible",
    "SurvivalFeatures",
    "SurvivalModel",
    "SurvivalRanking",
    "features_from_metrics",
    "load_survival_model",
]
