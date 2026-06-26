# intent: the PREDICTION-LANE leakage gate — run the standing leakage tripwire (research/leakage_tripwire.py) on a
# Polymarket cell's OWN point-in-time odds (and, when present, resolution) series BEFORE the cell can be funded.
# The tripwire is the #1 blow-up guard ([[vibe_coding_leakage_risk]]): a look-ahead/alignment bug UPSTREAM of the
# Gate is Gate-INVISIBLE (the Gate validates edge-after-costs, not pipeline honesty). The prediction lane is the
# newest data path (per-conditionId odds + UMA resolution settlement), so its odds/resolution features MUST clear
# the three-disconfirmer tripwire (available_at audit + shuffle-null + forward-shift sanity) as the price of
# admission — exactly the policy the readiness report's Fix-C asks for. PROPOSE-ONLY: a PASS is necessary, never
# sufficient; the deterministic Gate alone disposes. Changes NO Gate constant, moves no money, no LLM, no I/O of
# its own (it reads AltDataPoint lists already pulled point-in-time and reuses audit_feature verbatim).

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.leakage_tripwire import TripwireReport, audit_feature

# The metrics the prediction lane reads back from the alt store (provider="polymarket"): the per-conditionId YES
# odds (daily) and its hourly variant. The resolution series is a SINGLE terminal $1/$0 point per market, so it
# carries no forward-IC to tripwire — its PIT honesty is asserted directly (see resolution_pit_ok below), not via
# the IC-based three-check harness.
_ODDS_METRICS = ("odds", "odds_60")
_RESOLUTION_METRIC = "resolution"


@dataclass(frozen=True)
class PredictionTripwireResult:
    """The PASS/FAIL verdict for ONE prediction cell's data honesty. `passed` is the AND of: the odds series
    cleared the three-check leakage tripwire, AND any resolution point is PIT-honest (available_at == the real
    resolution ts, and the value is a clean binary $1/$0). A cell that fails must NOT be funded — its backtest
    number (and its resolution settlement) cannot be trusted. PROPOSE-ONLY: a PASS is the price of admission to
    the Gate, never a substitute for it."""

    condition_id: str
    metric: str
    odds_report: TripwireReport | None
    resolution_pit_ok: bool
    passed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        head = f"PREDICTION TRIPWIRE — {self.condition_id} [{self.metric}]: {'PASS' if self.passed else 'FAIL'}"
        lines = [head]
        if self.odds_report is not None:
            lines.append(self.odds_report.render())
        lines.append(f"  resolution PIT-honest: {self.resolution_pit_ok}")
        if self.reasons:
            lines.append(f"  REASONS: {', '.join(self.reasons)}")
        return "\n".join(lines)


def resolution_pit_ok(points: list[AltDataPoint]) -> bool:
    """A resolution series is PIT-honest iff EVERY point is (a) a clean binary payout (value within epsilon of 0.0
    or 1.0 — never a still-trading mid-odds masquerading as a settlement) AND (b) stamped at its real resolution
    time, i.e. available_at == ts (the payout is knowable ONLY once the chain resolved; an available_at EARLIER
    than ts would hand a backtest the outcome before it happened — the cardinal prediction-lane look-ahead). An
    empty series (the market hasn't resolved yet) is vacuously honest: there is simply no settlement to apply."""
    for p in points:
        if not (abs(p.value - 1.0) <= 1e-6 or abs(p.value - 0.0) <= 1e-6):
            return False  # not a clean $1/$0 payout
        if p.available_at < p.ts:
            return False  # the outcome was 'knowable' before it happened — a settlement look-ahead
    return True


def audit_prediction_cell(
    *,
    condition_id: str,
    odds_points: list[AltDataPoint],
    bars: list[Bar],
    resolution_points: list[AltDataPoint] | None = None,
    metric: str = "odds",
    horizon: int = 1,
    shuffle_trials: int = 200,
    seed: int = 0,
) -> PredictionTripwireResult:
    """Gate ONE prediction cell's data through the standing leakage tripwire before it may be funded.

    `odds_points` is the cell's OWN per-conditionId YES-odds series (provider="polymarket", symbol=conditionId,
    metric="odds"/"odds_60") read point-in-time; `bars` are the same cell's odds bars; `resolution_points` is the
    cell's resolution series (metric="resolution") when present. Runs `audit_feature` (available_at audit +
    shuffle-null + forward-shift sanity) on the odds series, and asserts the resolution series is PIT-honest. The
    cell PASSES iff both clear. PROPOSE-ONLY — the Gate alone disposes."""
    reasons: list[str] = []
    odds_report: TripwireReport | None = None
    if odds_points and bars:
        odds_report = audit_feature(
            odds_points, bars, horizon=horizon, feature=f"{condition_id}:{metric}",
            shuffle_trials=shuffle_trials, seed=seed,
        )
        if not odds_report.passed:
            reasons.append(f"odds_tripwire:{','.join(odds_report.failed_checks)}")
    else:
        # No odds / no bars → nothing to test honestly. Refuse rather than bless an empty cell.
        reasons.append("no_odds_to_audit")

    res_ok = resolution_pit_ok(resolution_points or [])
    if not res_ok:
        reasons.append("resolution_not_pit_honest")

    passed = (odds_report is not None and odds_report.passed) and res_ok
    return PredictionTripwireResult(
        condition_id=condition_id,
        metric=metric,
        odds_report=odds_report,
        resolution_pit_ok=res_ok,
        passed=passed,
        reasons=tuple(reasons),
    )


__all__ = [
    "PredictionTripwireResult",
    "audit_prediction_cell",
    "resolution_pit_ok",
]
