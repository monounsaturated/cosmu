# intent: registry of Pine *indicators* ported to computed data sources (the second Pine-import mode). Every
# future indicator-style Pine script (one whose output number IS the signal) lands here as a module exposing a
# `compute(bars, **params) -> IndicatorResult`, and is registered in INDICATORS so the CLI / correlation harness
# can find it by name. Strategy-style Pine (entry/exit rules) still goes through strategy/pine.py -> StrategySpec.

from __future__ import annotations

from cosmu.research.pine_indicators import ml_liquidity_zone
from cosmu.research.pine_indicators.base import (
    CorrelationReport,
    IndicatorResult,
    PineIndicator,
    correlate,
    forward_abs_return,
    forward_return,
)

# name -> the module's compute function. The registry is the single source of truth for "which Pine indicators
# have a clean Python port" — keep it in lockstep with the modules in this package.
INDICATORS = {
    ml_liquidity_zone.name: ml_liquidity_zone.compute,
}

__all__ = [
    "INDICATORS",
    "CorrelationReport",
    "IndicatorResult",
    "PineIndicator",
    "correlate",
    "forward_abs_return",
    "forward_return",
]
