from __future__ import annotations

from pydantic import BaseModel

# ---- autonomy: the human-overseen master tick (engine builds, web consumes) ----


class TickSummary(BaseModel):
    authored: int
    gated_passed: int
    funded: int
    recommendations: int


class AutonomyStatusResponse(BaseModel):
    """The human-overview snapshot of the autonomous master tick. `running` = armed (not paused); the loop is
    cron-driven (one tick per call), so there is no 24/7 daemon. `live_enabled` is reported but the tick never
    arms live — money-adjacent stays gated."""

    running: bool
    paused: bool
    live_enabled: bool
    cycles_run: int
    last_tick_at: str | None
    last_action: str
    next_action: str
    last_summary: TickSummary


class AutonomyPauseResponse(BaseModel):
    paused: bool


class AutonomyTickResponse(BaseModel):
    authored: int
    gated_passed: int
    funded: int
    recommendations: int


class AutonomyTickAcceptedResponse(BaseModel):
    job_id: str
    status: str  # always "running" on 202


class AutonomyTickJobResponse(BaseModel):
    job_id: str
    status: str  # "running" | "done" | "error"
    result: AutonomyTickResponse | None = None
    error: str | None = None


class RecommendationActionResponse(BaseModel):
    ok: bool
    applied: bool = False
    reason: str | None = None
