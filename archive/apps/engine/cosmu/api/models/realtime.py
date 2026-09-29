# intent: typed responses for the realtime-worker status surface; inputs: none; outputs: Pydantic models the
# OpenAPI/TS contracts generate from; invariants: nullable fields stay null when the worker has never beaten
# (honest empty — "no heartbeat yet" is a state, not a zero).

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RealtimeStatusResponse(BaseModel):
    """The worker's visible pulse. `enabled` mirrors the env toggle; `status` is derived server-side:
    'off' (disabled, no expectation of beats) · 'fresh' (last beat within the stale threshold) ·
    'stale' (enabled but the last beat is old — the badge state) · 'never' (enabled, no beat recorded)."""

    enabled: bool
    status: str
    last_heartbeat_at: str | None = None
    seconds_since_heartbeat: float | None = None
    stale_after_seconds: float
    consumers: dict[str, Any] | None = None  # per-consumer snapshots from the last beat's payload
