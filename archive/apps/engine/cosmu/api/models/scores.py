from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- Scores cockpit: per-source + composite INDEX scores grouped by category. ----
# Honest: a category/source with no ingested data reports connected=False and index_score=null (never a
# fabricated score). A key-gated source whose key is absent on the engine shows disabled=True so the UI
# greys it out. Reviews are DETERMINISTIC plain-language reads — never on the gate/scoring/money path.


class ScoreSourceRow(BaseModel):
    """One source inside a cockpit category.

    `connected` is True iff data has been ingested (status != "no data"). `key_required` marks a source
    that needs a provider key to return data; `key_present` is whether that key is set on the engine env;
    `disabled` = key_required AND NOT key_present (the UI greys it out). `review` is a plain-language read."""

    source: str
    category: str
    features: list[str]
    last_at: str | None = None
    freshness_label: str
    status: Literal["fresh", "recent", "aging", "stale", "no data"]
    trust_score: float
    tier: str
    hours_since: float | None = None
    connected: bool
    key_required: bool
    key_name: str | None = None
    key_present: bool
    disabled: bool
    review: str


class ScoreCategory(BaseModel):
    """A cockpit category (crypto · social · macro · OSINT · metals/forex) with a composite INDEX over the
    sources that actually have data. `index_score` is null when nothing is live (honest offline)."""

    key: str
    label: str
    index_score: float | None = None
    status: str  # "fresh" | "recent" | "aging" | "stale" | "no data" | "offline"
    freshness_label: str
    connected: bool
    live_sources: int
    total_sources: int
    review: str
    sources: list[ScoreSourceRow]


class ScoresResponse(BaseModel):
    """The scores cockpit: per-source + per-category + one composite INDEX, each with freshness and a
    plain-language review. `composite_index` is null when no category is live — never fabricated."""

    as_of: str
    composite_index: float | None = None
    composite_status: str
    composite_review: str
    categories: list[ScoreCategory]
