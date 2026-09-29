# intent: the realtime-worker STATUS route (realtime-data-lane epic P3) — the staleness contract made
# visible: 'a stale heartbeat is a badge, not a silent failure'. inputs: the events ledger's newest
# realtime_heartbeat row + the env toggle; outputs: RealtimeStatusResponse; invariants: read-only, no LLM,
# honest states ('off' when disabled, 'never' when enabled-but-silent — never a fabricated freshness), and
# a not-yet-migrated DB degrades to 'never' rather than a 500.

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from cosmu.api._shared import settings, store
from cosmu.api.models import RealtimeStatusResponse

router = APIRouter()

# Heartbeats land every ~60s; 5 minutes of silence = the worker is down/wedged (epic §3 badge threshold).
STALE_AFTER_SECONDS = 300.0


@router.get("/realtime/status", response_model=RealtimeStatusResponse)
def realtime_status() -> RealtimeStatusResponse:
    enabled = bool(getattr(settings, "realtime_worker_enabled", False))
    try:
        from cosmu.realtime.worker import latest_heartbeat

        beat = latest_heartbeat(store)
    except Exception:  # noqa: BLE001 — a missing table / DB blip is an honest 'never', not a 500
        beat = None
    if beat is None:
        return RealtimeStatusResponse(
            enabled=enabled, status="off" if not enabled else "never",
            stale_after_seconds=STALE_AFTER_SECONDS,
        )
    ts = datetime.fromisoformat(beat["ts"])
    age = (datetime.now(tz=UTC) - ts).total_seconds()
    status = "off" if not enabled else ("fresh" if age <= STALE_AFTER_SECONDS else "stale")
    return RealtimeStatusResponse(
        enabled=enabled, status=status, last_heartbeat_at=beat["ts"],
        seconds_since_heartbeat=age, stale_after_seconds=STALE_AFTER_SECONDS,
        consumers=(beat["payload"] or {}).get("consumers"),
    )
