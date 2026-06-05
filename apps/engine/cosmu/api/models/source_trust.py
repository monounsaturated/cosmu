from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- Source-trust scoreboard: freshness × realized gate contribution per data source. ----
# Honest: abstains (trust_score=0, status="no data") when a source has no data ingested.
# Never fabricates; no LLM on this path. The gate/money path is deterministic and separate.


class SourceTrustRow(BaseModel):
    """Trust metadata for one data source in plain English.

    `source` is the registry source string (e.g. "alternative.me", "fred", "news").
    `features` is the list of feature names served by this source.
    `last_at` is the latest availability time across all metrics for this source (ISO-8601 UTC, or null).
    `freshness_label` is plain-language freshness, e.g. "fresh 4 h", "aging 3 d", "stale 10 d", "no data".
    `status` is the badge bucket: "fresh" | "recent" | "aging" | "stale" | "no data".
    `gate_pass_count` is the number of gate-passed backtests that used any feature from this source.
    `trust_score` is a normalized [0, 1] composite (freshness × gate contribution).
    `summary` is a one-liner in plain English for the scoreboard card.
    `tier` is "tier0" or "tier1" (tier0 = higher-confidence, tier1 = low-confidence until validated OOS).
    `hours_since` is hours since last fresh data (null when no data)."""

    source: str
    features: list[str]
    last_at: str | None = None
    freshness_label: str
    status: Literal["fresh", "recent", "aging", "stale", "no data"]
    gate_pass_count: int
    trust_score: float
    summary: str
    tier: str
    hours_since: float | None = None


class SourceTrustResponse(BaseModel):
    """The source-trust scoreboard: one row per registered data source, sorted best-first.
    Honest: a source with no data ingested yet shows trust_score=0, status="no data"."""

    as_of: str
    rows: list[SourceTrustRow]
