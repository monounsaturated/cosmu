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
# T2  SHIPPED (this module): fractional-Kelly self-sizing from the Gate's DEFLATED edge, as a FROZEN funding-time
#     multiplier MULTIPLIED ON TOP of the T1 envelope (exactly like tracks.exposure_factor) — see
#     `kelly_size_multiplier`. NOT threaded inside size_fraction, so size_fraction stays the gate-verified physics
#     and backtest==forward parity holds. Derived from the deflated-Sharpe PROBABILITY (not the raw, overfit-prone
#     Sharpe — that is the whole point) and applied PER CELL on the cell's OWN standalone slice. This is NOT the
#     removed pooled `rotate`/capped-Kelly-pool allocator (which competed capital ACROSS strategies); it only
#     decides how much of a single cell's own slice to deploy. The portfolio-axis SIGNAL-crowding clamp that pairs
#     with it (Khandani-Lo) lives in master/signal_crowding.py and reuses this multiplier.
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

# ── T2 fractional-Kelly constants (LOCKED — sizing constants are NEVER survival knobs / never in param_space) ──
# Half-Kelly is the prudent fractional-Kelly standard: full Kelly maximises long-run log-growth but is famously
# fragile to a mis-estimated edge (one bad μ/σ and it over-bets into ruin); half-Kelly keeps ~3/4 of the growth at
# far lower drawdown. We compound the prudence by deriving the edge from the DEFLATED Sharpe (below), because the
# raw Sharpe is exactly the number overfitting inflates.
_KELLY_SCALE: float = 0.5
# A gate-passed cell never sizes below 10% of its T1 envelope — it must keep deploying a real, scoreable forward
# stream (the forward/paper test is the fluke safeguard; a cell sized to dust can't prove or disprove itself).
_KELLY_FLOOR: float = 0.10


def _clamp01(x: float) -> float:
    return max(0.0, min(float(x), 1.0))


def kelly_size_multiplier(
    deflated_edge: float,
    *,
    kelly_scale: float = _KELLY_SCALE,
    floor: float = _KELLY_FLOOR,
) -> float:
    """Fractional-Kelly capital multiplier in [floor, kelly_scale] derived from the Gate's DEFLATED edge.

    `deflated_edge` is the deflated-Sharpe PROBABILITY in [0, 1] (master/scorer.deflated_sharpe_prob — persisted as
    backtests.deflated_sharpe and carried as Track.rolling_dsr): P(true per-obs Sharpe > the trial-count-inflated
    benchmark). It already prices in non-normality AND how hard we searched (the effective trial count), so sizing
    on it — never on the raw in-sample Sharpe — refuses to bet big on an edge that only looks good because we looked
    a lot. Deriving Kelly from the DEFLATED edge is the entire point: the un-deflated Sharpe is the quantity that
    overfitting inflates, so it is the worst possible thing to lever on.

    Fractional (half-)Kelly: a maximal-confidence edge (deflated_edge → 1) deploys `kelly_scale` (default 0.5) of
    its T1 vol-target envelope; a barely-confirmed edge deploys proportionally less, floored at `floor` so a passed
    cell still produces a scoreable forward stream. Monotone non-decreasing in the edge.

    Applied as a FROZEN funding-time scalar MULTIPLIED ON TOP of `size_fraction` (the same seam as
    tracks.exposure_factor) — NOT threaded inside it — so size_fraction stays the exact gate-verified physics and
    the backtest==forward==live parity (audit #7) is preserved. PER-CELL + self-funding: this scales a cell's OWN
    standalone slice from ITS OWN edge; it is NOT a pooled cross-strategy allocator (the removed `rotate` /
    capped-Kelly-pool concept that competed capital across strategies). PURE: no I/O, no DB, deterministic.
    """
    edge = _clamp01(deflated_edge)
    scale = max(0.0, float(kelly_scale))
    return max(float(floor), scale * edge)


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


def _concurrency_divisor(spec: StrategySpec, open_positions: int) -> float:
    """How much the per-position cap divides this track's slice, given how many positions are ALREADY open.

    SANDBOX per-combo model: the slice is the strategy's to deploy as it chooses (an all-in mono-position spec
    is legitimate). The `1/max_concurrent_positions` term exists ONLY so that several CONCURRENT positions don't
    over-deploy the slice in sum — it must NOT bridle a position taken while the book is otherwise flat.

    - `open_positions <= 1` (the default / a mono-position entry): divisor 1.0 — the spec sizes its slice freely,
      bounded only by its own `max_position_pct`, never forced to 1/N.
    - `open_positions >= 2`: divide by the number actually open (capped at `max_concurrent_positions`), so the
      sum of concurrent legs stays within the slice. This binds only when concurrency is REAL, not hypothetical.
    """
    max_concurrent = max(1, int(spec.risk.max_concurrent_positions))
    concurrent = min(max(1, int(open_positions)), max_concurrent)
    return float(concurrent)


def size_fraction(
    spec: StrategySpec,
    *,
    closes: list[float] | None = None,
    target_vol: float | None = None,
    open_positions: int = 1,
) -> float:
    """Fraction of THIS track's capital slice to deploy on one entry signal.

    `open_positions` is how many positions THIS track already holds (the entry being sized included as ≥1).
    SANDBOX per-combo model: the `1/max_concurrent_positions` term divides the slice ONLY when several positions
    are genuinely open at once (open_positions ≥ 2) — a MONO-position all-in spec (the default, open_positions≤1)
    is never bridled to 1/N and deploys its whole slice if max_position_pct/conviction say so. The per-combo
    wallet (master/risk) is what bounds loss, not a blanket fraction.

    T1 path — closes AND target_vol provided (track funded with T1):
        realized_vol = EWMA(λ=0.94) from trailing closes (bar-frequency)
        cap = min(max_position_pct, 1/concurrency_divisor, 1.0)   # divisor 1.0 unless ≥2 legs are open
        f = clamp( target_vol / max(realized_vol, VOL_FLOOR) × conviction, SIZING_FLOOR, cap )

    T0 path — no closes or no target_vol (track funded pre-T1, or backtest gate path):
        f = clamp( max_position_pct / concurrency_divisor ) × clamp(conviction)

    PURE by contract — no I/O, no DB, no settings, no randomness.
    """
    divisor = _concurrency_divisor(spec, open_positions)
    if closes is not None and target_vol is not None and target_vol > 0:
        realized_vol = _ewma_vol_from_closes(closes)
        if realized_vol is not None and realized_vol > 0:
            cap = min(_clamp01(spec.risk.max_position_pct), 1.0 / divisor, 1.0)
            f = (target_vol / max(realized_vol, _VOL_FLOOR)) * _clamp01(spec.risk.conviction)
            return float(max(_SIZING_FLOOR, min(f, cap)))
    # T0 fallback — the slice fraction, divided only when concurrency is real (divisor 1.0 for a mono position).
    return _clamp01(spec.risk.max_position_pct / divisor) * _clamp01(spec.risk.conviction)
