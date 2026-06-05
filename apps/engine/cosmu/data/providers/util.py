from __future__ import annotations

import math


def rolling_zscore(values: list[float | None], lookback: int) -> list[float | None]:
    """Causal z-score: only past+current values, never the full sample (a full-sample z is lookahead)."""
    out: list[float | None] = [None] * len(values)
    window: list[float] = []
    for idx, value in enumerate(values):
        if value is None:
            window = []
            continue
        window.append(value)
        if len(window) > lookback:
            window.pop(0)
        if len(window) >= max(2, lookback):
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            sd = math.sqrt(var)
            out[idx] = (value - mean) / sd if sd else 0.0
    return out
