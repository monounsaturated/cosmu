# intent: human-overseen autonomous master tick; inputs: pause/resume/tick; outputs: status + async job results; invariants: live STAYS OFF — the tick never arms live, sim fills only.

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from cosmu.api._shared import _brain_reference_bars, store
from cosmu.api.models import (
    AutonomyPauseResponse,
    AutonomyStatusResponse,
    AutonomyTickAcceptedResponse,
    AutonomyTickJobResponse,
    AutonomyTickResponse,
)

logger = logging.getLogger("cosmu.api.autonomy")
router = APIRouter()


def _autonomy_status_response() -> AutonomyStatusResponse:
    from cosmu.api.models import TickSummary as _TickSummary
    from cosmu.master.scheduler import autonomy_status

    st = autonomy_status(store)
    return AutonomyStatusResponse(
        running=st.running,
        paused=st.paused,
        live_enabled=st.live_enabled,
        cycles_run=st.cycles_run,
        last_tick_at=st.last_tick_at,
        last_action=st.last_action,
        next_action=st.next_action,
        last_summary=_TickSummary(
            authored=st.last_summary.authored,
            gated_passed=st.last_summary.gated_passed,
            funded=st.last_summary.funded,
            recommendations=st.last_summary.recommendations,
        ),
    )


@router.get("/autonomy/status", response_model=AutonomyStatusResponse)
def autonomy_status_route() -> AutonomyStatusResponse:
    """The human-overview snapshot of the autonomous master tick — running/paused, live on/off (reported, never
    armed here), cycles run, and the last tick's headline counts. Read entirely off the persisted ledger.

    All four reads share ONE autocommit Postgres connection (store.reading()) — without this each store.row()
    opens + closes a separate psycopg2 connection (~1s RTT × 4 ≈ 6–7s, over the 5s frontend budget)."""
    with store.reading():
        return _autonomy_status_response()


@router.post("/autonomy/pause", response_model=AutonomyPauseResponse)
def autonomy_pause() -> AutonomyPauseResponse:
    from cosmu.master.scheduler import pause

    pause(store)
    return AutonomyPauseResponse(paused=True)


@router.post("/autonomy/resume", response_model=AutonomyPauseResponse)
def autonomy_resume() -> AutonomyPauseResponse:
    from cosmu.master.scheduler import resume

    resume(store)
    return AutonomyPauseResponse(paused=False)


# In-memory job registry for async tick dispatch.  Single-process; Railway restarts clear it,
# which is fine — the events ledger is the durable record.
_tick_jobs: dict[str, dict] = {}


def _run_tick_job(job_id: str) -> None:
    """Background worker: runs the tick and writes the result into _tick_jobs."""
    from cosmu.master.scheduler import run_tick

    try:
        report = run_tick(store, n=6, seed=7, edge_market=False)
        try:
            from cosmu.mind import reflect

            reflect(store, reference_bars=_brain_reference_bars())
        except Exception:  # noqa: BLE001 — reflection is best-effort
            pass
        s = report.summary
        _tick_jobs[job_id] = {
            "status": "done",
            "result": AutonomyTickResponse(
                authored=s.authored,
                gated_passed=s.gated_passed,
                funded=s.funded,
                recommendations=s.recommendations,
            ),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        # Surface only the exception TYPE to the client (str(exc) can leak DSNs / file paths / internals);
        # the full detail stays server-side in the logs for debugging.
        logger.exception("autonomy tick job %s failed", job_id)
        _tick_jobs[job_id] = {"status": "error", "result": None, "error": type(exc).__name__}


@router.post("/autonomy/tick", response_model=AutonomyTickAcceptedResponse, status_code=202)
def autonomy_tick(background_tasks: BackgroundTasks) -> AutonomyTickAcceptedResponse:
    """Enqueue ONE bounded, idempotent, audited autonomous cycle and return 202 immediately.
    The cycle (ingest → author → DETERMINISTIC gate + flywheel → fund → recommend) runs in the
    background so Railway's gateway never times out.  Poll GET /autonomy/tick/{job_id} for the result.
    LIVE STAYS OFF — sim fills only; the tick never arms live."""
    job_id = str(uuid.uuid4())
    _tick_jobs[job_id] = {"status": "running", "result": None, "error": None}
    background_tasks.add_task(_run_tick_job, job_id)
    return AutonomyTickAcceptedResponse(job_id=job_id, status="running")


@router.get("/autonomy/tick/{job_id}", response_model=AutonomyTickJobResponse)
def autonomy_tick_job(job_id: str) -> AutonomyTickJobResponse:
    """Poll the result of an async tick dispatch.  Returns status: running | done | error."""
    job = _tick_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="tick job not found")
    return AutonomyTickJobResponse(job_id=job_id, **job)
