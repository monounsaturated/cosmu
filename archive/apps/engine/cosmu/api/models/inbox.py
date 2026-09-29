from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- idea inbox (natural-language strategy intake) ----


class InboxIdeaRequest(BaseModel):
    text: str
    name: str | None = None


class InboxIdeaResponse(BaseModel):
    ok: bool
    filename: str
    name: str
    queued: int  # ideas still waiting for the next scan to turn them into gated specs
    note: str


class InboxQueueItem(BaseModel):
    filename: str
    name: str
    ts: str
    status: Literal["queued", "imported"]


class InboxQueueResponse(BaseModel):
    items: list[InboxQueueItem]
    inbox_dir: str
