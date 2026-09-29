# intent: the READ-ONLY lifecycle-trace detail endpoint — one composed view of a strategy version's
# backtest → paper → forward → live-ready journey. inputs: a version_id (path); outputs: the composed
# live-eligibility + paper-maturity + current-regime verdicts PLUS the version's lifecycle audit trace read
# off the existing events ledger. invariants: read-only (never writes, never gates, never arms money — it only
# COMPOSES the existing deterministic verdicts that master/live_eligibility already owns); reuses the same
# verdict functions the live-arming path uses, so the surface can never disagree with the gate; missing
# evidence renders honestly (the verdicts already fail safe). Response models are defined locally (not in the
# shared models package) to keep this purely additive — no shared contract is modified.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from cosmu.api._shared import _json, _version_reference_bars, store
from cosmu.master.lifecycle import LIFECYCLE_KINDS, LIFECYCLE_ORDER
from cosmu.master.live_eligibility import live_eligibility_verdict

router = APIRouter()


class RegimeView(BaseModel):
    label: str
    vol_bucket: str
    trend: str


class LiveEligibilityView(BaseModel):
    eligible: bool
    forward_ready: bool
    paper_age_days: float
    net_return_pct: float
    min_days: int
    regime_eligible: bool
    proven_regimes: list[str]
    overridden: bool
    reason: str


class PaperMaturityView(BaseModel):
    paper_age_days: float
    net_return_pct: float
    live_ready: bool
    min_days: int


class LifecycleMark(BaseModel):
    """One audit mark on the version's journey, read off the events ledger."""

    kind: str
    ts: str
    actor: str
    payload: dict[str, Any]


class ReadinessResponse(BaseModel):
    """The composed lifecycle-trace detail for one version: the three existing verdicts (live-eligibility,
    paper maturity, current regime) PLUS the ordered lifecycle audit trace and the latest stage reached. This is
    an advisory READ — it never arms money; the live-arming interlocks remain the sole authority."""

    version_id: str
    stage: str | None  # the latest lifecycle stage reached (by LIFECYCLE_ORDER), None if no marks yet
    eligible: bool  # convenience mirror of live_eligibility.eligible
    current_regime: RegimeView
    live_eligibility: LiveEligibilityView
    paper_maturity: PaperMaturityView
    trace: list[LifecycleMark]


def _latest_stage(marks: list[LifecycleMark]) -> str | None:
    """The furthest-along stage the version has reached, by LIFECYCLE_ORDER (NOT by recency): a strategy that
    was killed after maturing still reports the terminal 'strategy_killed' stage because it sorts last. None
    when the trace is empty (no lifecycle marks recorded yet)."""
    order = {kind: i for i, kind in enumerate(LIFECYCLE_ORDER)}
    reached = [m.kind for m in marks if m.kind in order]
    if not reached:
        return None
    return max(reached, key=lambda k: order[k])


@router.get("/readiness/{version_id}", response_model=ReadinessResponse)
def readiness_detail(version_id: str) -> ReadinessResponse:
    """Compose the three existing deterministic verdicts for one version into a single lifecycle-trace view,
    and attach its audit trace from the events ledger. Read-only: reuses live_eligibility_verdict (which itself
    composes paper_maturity + current_regime), so this surface can never disagree with the live-arming gate. All
    reads share one connection."""
    reference = _version_reference_bars(version_id)  # this version's own asset-class regime brain (not BTC for all)
    with store.reading():
        verdict = live_eligibility_verdict(store, version_id, reference)
        rows = store.rows(
            "SELECT ts, actor, kind, payload FROM events WHERE ref_id = ? AND kind IN "
            f"({','.join('?' for _ in LIFECYCLE_KINDS)}) ORDER BY id ASC",
            (version_id, *sorted(LIFECYCLE_KINDS)),
        )

    trace = [
        LifecycleMark(
            kind=r["kind"],
            ts=r["ts"],
            actor=r["actor"],
            payload=_json(r["payload"]) if isinstance(_json(r["payload"]), dict) else {},
        )
        for r in rows
    ]
    regime = verdict.current_regime
    return ReadinessResponse(
        version_id=version_id,
        stage=_latest_stage(trace),
        eligible=verdict.eligible,
        current_regime=RegimeView(label=regime.label, vol_bucket=regime.vol_bucket, trend=regime.trend),
        live_eligibility=LiveEligibilityView(
            eligible=verdict.eligible,
            forward_ready=verdict.forward_ready,
            paper_age_days=verdict.paper_age_days,
            net_return_pct=verdict.net_return_pct,
            min_days=verdict.min_days,
            regime_eligible=verdict.regime_eligible,
            proven_regimes=verdict.proven_regimes,
            overridden=verdict.overridden,
            reason=verdict.reason,
        ),
        paper_maturity=PaperMaturityView(
            paper_age_days=verdict.paper_age_days,
            net_return_pct=verdict.net_return_pct,
            live_ready=verdict.forward_ready,
            min_days=verdict.min_days,
        ),
        trace=trace,
    )
