# Position-sizing — ONE shared leaf module.
# Called identically from backtest._entry_notional, paper_step (forward), and live execution so that
# tracks.return_pct (what live_eligibility reads) runs the physics the gate proved.
#
# ROADMAP (do NOT add knobs to param_space — sizing constants are never survival knobs):
#
# T0  SHIPPED: static fraction = clamp(max_position_pct) × clamp(conviction)  [this file]
#
# T1  NEXT — vol-target envelope (frequency-aware, per-track):
#     f = clamp( target_vol / max(ewma_vol, VOL_FLOOR) × conviction, SIZING_FLOOR, cap )
#     cap = min(max_position_pct, 1/max_concurrent_positions, 1.0)  [spot: no leverage]
#     target_vol = median realized_vol of strategy's OWN backtest bar_returns, FROZEN at funding
#                  (+1 tracks column; re-screen required when T1 is activated)
#     realized_vol = EWMA(λ≈0.94) of trailing closes, computed PIT at decision bar
#     New sig: size_fraction(spec, *, closes, conviction_mult=1.0)
#     WARNING: T1 must REPLACE `frac` in backtest._entry_notional — do NOT thread vol through
#              size_series/_size_at (that seam is a multiplier → double-count).
#
# T2  DEFERRED — fractional Kelly × √N shrink as a frozen funding-time multiplier on the T1 envelope.
#     Needs per-trade μ/σ in BacktestMetrics (2 cols). Do NOT reuse sharpe_per_obs (per-bar, wrong base).
#
# T3  PREMATURE — book-level ERC across the bankroll. Blocker: no starting_capital in loop.register_track.
#
from __future__ import annotations

from cosmu.strategy.spec import StrategySpec


def _clamp01(x: float) -> float:
    return max(0.0, min(float(x), 1.0))


def size_fraction(spec: StrategySpec) -> float:
    """Fraction of THIS track's capital slice to deploy on one entry signal.

    Tier 0: clamp(max_position_pct) × clamp(conviction), ∈ [0, 1] (hard spot cap).
    PURE by contract — depends only on spec.risk, never on settings / market / clock.
    """
    return _clamp01(spec.risk.max_position_pct) * _clamp01(spec.risk.conviction)
