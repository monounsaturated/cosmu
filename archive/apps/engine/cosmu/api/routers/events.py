# intent: audited event ledger read; inputs: limit; outputs: EventsResponse; invariants: read-only over the append-only events table.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import _json, store
from cosmu.api.models import Event, EventsResponse

router = APIRouter()


@router.get("/events", response_model=EventsResponse)
def events(limit: int = 50) -> EventsResponse:
    rows = store.rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    return EventsResponse(events=[Event(id=row["id"], ts=row["ts"], actor=row["actor"], kind=row["kind"], ref_type=row["ref_type"], ref_id=row["ref_id"], payload=_json(row["payload"])) for row in rows])
