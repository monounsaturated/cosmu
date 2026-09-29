from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- News/intel panel: recent scored news events (typed, dated, point-in-time). ----


class NewsEventRow(BaseModel):
    """One recent scored news event from the `news_event_score` alt-data series.

    `ts` and `available_at` are ISO-8601 UTC strings (point-in-time, no look-ahead).
    `value` is the signed magnitude in [-1, 1] (sign × magnitude; the gate-readable number).
    `event_type` is the human-readable label ("bullish" / "bearish" / "neutral") derived from sign.
    `symbol` is the ticker this event was scored for (e.g. "BTCUSDT")."""

    ts: str | None = None
    available_at: str | None = None
    value: float
    event_type: Literal["bullish", "bearish", "neutral"]
    symbol: str


class NewsIntelResponse(BaseModel):
    """The news/intel panel: recent scored events, newest first.
    Honest empty state when no news has been ingested yet."""

    symbol: str
    events: list[NewsEventRow]
