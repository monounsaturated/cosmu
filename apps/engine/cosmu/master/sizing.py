# Position-sizing — ONE shared leaf module.
# Called identically from backtest._entry_notional, paper_step (forward), and live execution so that
# tracks.return_pct (what live_eligibility reads) runs the physics the gate proved.
#
# ROADMAP (do NOT add knobs to param_space — sizing constants are never survival knobs):
#
# T0  SHIPPED: static fraction = clamp(max_position_pct) × clamp(conviction)
#
# T1  SHIPPED: vol-target envelope (frequency-aware, per-track)
#     f = clamp( target_vol / max(ewma_vol(closes), VOL_FLOOR) × conviction, SIZING_FLOOR, cap )
#     cap = min(max_position_pct, 1/max_concurrent_positions, 1.0)  [spot: no leverage]
#     target_vol = median(EWMA vol series) of price returns over the backtest VALIDATION bars,
#                  FROZEN at funding → tracks.target_vol (+1 column, NULL = T0 fallback).
#     Activation: all funded tracks have target_vol=NULL → T0 until re-screened with T1.
#     WARNING: T1 uses size_fraction(spec, closes=..., target_vol=...) — the backtest _entry_notional
#              still delegates through size_fraction BUT passes no closes → T0 path in the gate,
#              keeping gate-verified physics. DO NOT thread vol through size_series/_size_at
#              (that seam MULTIPLIES → double-count trap).
#
# T2  DEFERRED — fractional Kelly × √N shrink as a frozen funding-time multiplier on the T1 envelope.
#     Needs per-trade μ/σ in BacktestMetrics (2 cols). Do NOT reuse sharpe_per_obs (per-bar, wrong base).
#
# T3  PREMATURE — book-level ERC across the bankroll. Blocker: no starting_capital in loop.register_track.
#
from __future__ import annotations

import math
import statistics as _stats

from cosmu.strategy.spec import StrategySpec

_EWMA_LAMBDA: float = 0.94
_VOL_FLOOR: float = 1e-6   # prevents division by zero; never binds in real assets
_SIZING_FLOOR: float = 0.001  # floor: never below 0.1% of the track slice


def _clamp01(x: float) -> float:
    return max(0.0, min(float(x), 1.0))


def compute_target_vol(price_returns: list[float]) -> float | None:
    """Compute the vol-target anchor from a price-return series (bar frequency, NOT annualized).

    Algorithm: EWMA(λ=0.94) seeded with the first `warmup` bars, then the MEDIAN of the running vol
    series is returned as the 'typical volatility fingerprint' for this strategy. Returns None when
    the series is too short (< warmup+1 bars). Called once per backtest and frozen in tracks.target_vol.
    """
    warmup = 20
    n = len(price_returns)
    if n < warmup + 1:
        return None
    var = sum(r * r for r in price_returns[:warmup]) / warmup
    vols: list[float] = []
    for r in price_returns[warmup:]:
        var = _EWMA_LAMBDA * var + (1 - _EWMA_LAMBDA) * r * r
        vols.append(math.sqrt(max(var, 0.0)))
    return float(_stats.median(vols)) if vols else None


def _ewma_vol_from_closes(closes: list[float], warmup: int = 20) -> float | None:
    """Compute current EWMA realized vol from a list of price levels (bar closes).

    Converts closes → simple returns, then applies EWMA(λ=0.94). Returns the final vol estimate
    (bar-frequency, NOT annualized). Returns None when there are fewer than warmup+2 closes.
    """
    if len(closes) < warmup + 2:
        return None
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) < warmup + 1:
        return None
    var = sum(r * r for r in returns[:warmup]) / warmup
    for r in returns[warmup:]:
        var = _EWMA_LAMBDA * var + (1 - _EWMA_LAMBDA) * r * r
    return math.sqrt(max(var, 0.0))


def size_fraction(
    spec: StrategySpec,
    *,
    closes: list[float] | None = None,
    target_vol: float | None = None,
) -> float:
    """Fraction of THIS track's capital slice to deploy on one entry signal.

    T1 path — closes AND target_vol provided (track funded with T1):
        realized_vol = EWMA(λ=0.94) from trailing closes (bar-frequency)
        cap = min(max_position_pct, 1/max_concurrent_positions, 1.0)
        f = clamp( target_vol / max(realized_vol, VOL_FLOOR) × conviction, SIZING_FLOOR, cap )

    T0 path — no closes or no target_vol (track funded pre-T1, or backtest gate path):
        f = clamp(max_position_pct) × clamp(conviction)

    PURE by contract — no I/O, no DB, no settings, no randomness.
    """
    if closes is not None and target_vol is not None and target_vol > 0:
        realized_vol = _ewma_vol_from_closes(closes)
        if realized_vol is not None and realized_vol > 0:
            max_concurrent = max(1, int(spec.risk.max_concurrent_positions))
            cap = min(_clamp01(spec.risk.max_position_pct), 1.0 / max_concurrent, 1.0)
            f = (target_vol / max(realized_vol, _VOL_FLOOR)) * _clamp01(spec.risk.conviction)
            return float(max(_SIZING_FLOOR, min(f, cap)))
    # T0 fallback
    return _clamp01(spec.risk.max_position_pct) * _clamp01(spec.risk.conviction)
