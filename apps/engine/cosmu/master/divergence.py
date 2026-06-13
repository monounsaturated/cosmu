# intent: the SIM-vs-BACKTEST divergence signal per paper track — an EARLY WARNING that a funded track's
# REAL marked forward return has stopped tracking the backtest it was funded on (alpha-decay / regime-shift).
# inputs: the track's marked forward return %, its paper age in days, the backtest OOS return % and the
# OOS window length in days; outputs: a status ("insufficient" | "tracking" | "diverging"), the signed gap in
# percentage points, and the expected forward return over the marked window. invariants: fully deterministic +
# LLM-free (pure arithmetic on returns + a clock); MONITORING ONLY — it NEVER gates, NEVER moves money, NEVER
# feeds the scorer/FDR survival path; it only ever SURFACES a calm read-out for the operator. The "diverging"
# threshold is the named DIVERGENCE_GAP_PCT constant, never an inline magic number, and is intentionally a
# monitoring band — it can never loosen any Gate interlock because it is not on the Gate path at all. Fails safe
# to "insufficient" (no alarm) whenever the marked window is too short or any input is missing/degenerate.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Below this many marked forward days a track has NOT accrued enough real history to compare against its backtest —
# the gap would be noise, so we honestly report "insufficient" (an empty state, never a false "diverging" alarm).
# A named constant, never an inline magic number. This is a DISPLAY floor for the warning, never a Gate threshold.
DIVERGENCE_MIN_DAYS: float = 5.0

# The monitoring band: the marked forward return is flagged "diverging" only once it falls SHORT of (or runs
# beyond) its backtest-implied expectation for the same window by more than this many percentage points. A named
# constant, never an inline magic number. This is purely a warning band on a read-out surface — it is NOT on the
# Gate/scorer/FDR/money path and therefore can never loosen any Gate interlock. Generous on purpose: this is an
# early-warning glance, not a kill switch.
DIVERGENCE_GAP_PCT: float = 5.0

DivergenceStatus = Literal["insufficient", "tracking", "diverging"]


@dataclass(frozen=True)
class Divergence:
    """The SIM-vs-backtest divergence read-out for one standalone paper track.

    `status`:
      - "insufficient": the marked window is too short (< DIVERGENCE_MIN_DAYS) or an input is missing/degenerate —
        we have no honest read yet, so we raise NO alarm (the empty state).
      - "tracking":      the marked forward return is within +/- DIVERGENCE_GAP_PCT of its backtest-implied
        expectation for the same elapsed window — the live track is still following its backtest.
      - "diverging":     |gap| exceeds DIVERGENCE_GAP_PCT — an early warning of alpha-decay / regime-shift; the
        operator should look. This is SURFACED, NEVER ENFORCED.

    `gap_pct`           = paper_return_pct - expected_return_pct (signed percentage points; negative = the live
                          track is UNDER-performing its backtest, the usual decay direction). 0.0 when insufficient.
    `expected_return_pct` = the backtest OOS return pro-rated to the marked forward window
                          (backtest_oos_return_pct * marked_days / backtest_oos_days). 0.0 when insufficient.
    `marked_days`       = the paper days actually used for the comparison (clamped at >= 0).
    """

    status: DivergenceStatus
    gap_pct: float
    expected_return_pct: float
    marked_days: float
    min_days: float = DIVERGENCE_MIN_DAYS
    gap_threshold_pct: float = DIVERGENCE_GAP_PCT


def _finite(value: object) -> float | None:
    """Coerce to a finite float, or None for anything missing/non-numeric/NaN/inf — so a degenerate input fails
    safe to the no-alarm "insufficient" branch rather than emitting a bogus gap."""
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN / +-inf
        return None
    return out


def divergence(
    paper_return_pct: object,
    paper_age_days: object,
    backtest_oos_return_pct: object,
    backtest_oos_days: object,
    *,
    min_days: float = DIVERGENCE_MIN_DAYS,
    gap_threshold_pct: float = DIVERGENCE_GAP_PCT,
) -> Divergence:
    """Compute the SIM-vs-backtest divergence for one paper track.

    The honest comparison is RATE-BASED: a 5-day forward return can only be compared to the backtest by pro-rating
    the backtest's total OOS return to the SAME 5-day window. We compute the backtest's expected return over the
    marked window as `backtest_oos_return_pct * marked_days / backtest_oos_days`, then report the signed gap
    (forward minus expected). The track is "diverging" only when |gap| > `gap_threshold_pct`.

    Fails safe to "insufficient" (NO alarm) when: the marked window is shorter than `min_days`; or any of the four
    inputs is missing/non-numeric/NaN/inf; or the backtest OOS window length is non-positive (can't pro-rate). This
    is a MONITORING read-out only — it never gates, never moves money, never touches the scorer/FDR/Gate path.
    """
    fwd = _finite(paper_return_pct)
    days = _finite(paper_age_days)
    bt_return = _finite(backtest_oos_return_pct)
    bt_days = _finite(backtest_oos_days)

    marked_days = days if (days is not None and days > 0) else 0.0

    # Too little marked history, or any missing/degenerate input → no honest read; raise no alarm.
    if (
        fwd is None
        or marked_days < min_days
        or bt_return is None
        or bt_days is None
        or bt_days <= 0.0
    ):
        return Divergence(
            status="insufficient",
            gap_pct=0.0,
            expected_return_pct=0.0,
            marked_days=marked_days,
            min_days=min_days,
            gap_threshold_pct=gap_threshold_pct,
        )

    # Pro-rate the backtest's total OOS return to the elapsed forward window so the two numbers are comparable.
    expected = bt_return * (marked_days / bt_days)
    gap = fwd - expected
    status: DivergenceStatus = "diverging" if abs(gap) > gap_threshold_pct else "tracking"
    return Divergence(
        status=status,
        gap_pct=round(gap, 4),
        expected_return_pct=round(expected, 4),
        marked_days=round(marked_days, 2),
        min_days=min_days,
        gap_threshold_pct=gap_threshold_pct,
    )
