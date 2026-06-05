# intent: chat-console policy intake; inputs: CommandRequest; outputs: CommandResponse; invariants: money-adjacent commands are recorded but never auto-applied.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import CommandRequest, CommandResponse
from cosmu.knowledge.store import utcnow

router = APIRouter()


@router.post("/console/command", response_model=CommandResponse)
def console_command(request: CommandRequest) -> CommandResponse:
    lowered = request.text.lower()
    parsed = {"raw": request.text, "scope": "policy", "requires_money_move": "live" in lowered or "cap" in lowered}
    applied = not parsed["requires_money_move"]
    store.insert(
        "policies",
        {"ts": utcnow(), "source": "chat", "raw_text": request.text, "parsed": parsed, "scope": "policy", "applied": int(applied), "applied_at": utcnow() if applied else None},
    )
    store.append_event(actor="human", kind="console_command", ref_type="policy", payload=parsed)
    reply = "Policy recorded and applied to research routing." if applied else "I parsed this as a money-adjacent change. It is recorded but requires explicit approval before applying."
    return CommandResponse(parsed_policy=parsed, applied=applied, reply_md=reply)
