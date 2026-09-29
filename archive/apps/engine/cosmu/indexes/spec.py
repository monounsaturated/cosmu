# intent: the typed definition of an INDEX — a named, point-in-time, deterministically-scored composite series
# the operator creates and (later) strategies key off. inputs: an operator/Claude-authored definition; outputs:
# a validated IndexSpec + its stable alt_data metric name; invariants: every index pins a FROZEN transform_version
# (same input → same score → STABLE ranking, the operator's hard requirement), the LLM (when used) standardizes
# text ONLY at compute time behind that version + a content-hash cache (NEVER on the gate/money path), the
# definition shape is validated per kind so a half-formed index can't land, and an empty/unkeyed source degrades
# honestly (no fabricated score). An index is data plumbing — it never funds or fires anything.

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Frozen scoring-transform version. Pinned into every stored point's provenance + the registry row, so a
# strategy later built on an index stays reproducible. BUMP this string when the scoring logic changes —
# old indexes keep their old version until recomputed, so history never silently re-scores.
INDEX_TRANSFORM_VERSION = "index-v1"

# The store provider bucket all index series live under (alt_data.provider). Routed for strategies via
# cosmu.indexes.routing.index_routes(store) — so an index is a first-class, key-off-able feature.
INDEX_PROVIDER = "index"

IndexKind = Literal["single_account", "social_bucket", "event_topic", "prompt_rubric"]
IndexStatus = Literal["draft", "active", "paused"]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,46}[a-z0-9]$")


class IndexSpec(BaseModel):
    """One operator-defined index. `kind` picks the source + scorer; `definition` carries the kind-specific
    payload (validated below). The series is stored in alt_data under provider='index', metric=`metric`,
    symbol='MARKET' (market-wide) or per entity. Authored once, then computed every cadence by the deterministic
    pipeline — the value is ALWAYS scored the same way for the same input (frozen transform_version)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="slug, stable: a-z 0-9 _ - (2..48 chars). The metric becomes idx_<id>.")
    name: str = Field(min_length=1, max_length=120)
    # The WHY — required, like a StrategySpec's rationale. Anti-slop: an index must declare what it measures
    # and why it should carry signal, on the record, before it can be created.
    rationale: str = Field(min_length=1, max_length=2000)
    kind: IndexKind
    definition: dict[str, Any] = Field(default_factory=dict)
    # The assets this index scores. Empty ⇒ a single MARKET-wide series (one number for the whole tape).
    entities: list[str] = Field(default_factory=list)
    # Frozen at author time; recompute under a new version is a deliberate act (history is never re-scored).
    transform_version: str = INDEX_TRANSFORM_VERSION
    cadence_minutes: int = Field(default=60, ge=5, le=1440)
    status: IndexStatus = "draft"
    created_at: str | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError("id must be a 2..48 char slug of [a-z0-9_-], not starting/ending with - or _")
        return v

    @model_validator(mode="after")
    def _validate_definition(self) -> IndexSpec:
        d = self.definition
        if self.kind in ("single_account", "social_bucket"):
            handles = d.get("handles")
            if not isinstance(handles, list) or not all(isinstance(h, str) and h.strip() for h in handles):
                raise ValueError(f"{self.kind} needs definition.handles = a non-empty list of handle strings")
            if self.kind == "single_account" and len(handles) != 1:
                raise ValueError("single_account needs exactly one handle (use social_bucket for several)")
            if self.kind == "social_bucket" and len(handles) < 1:
                raise ValueError("social_bucket needs at least one handle")
        elif self.kind == "event_topic":
            topic = d.get("topic")
            if not isinstance(topic, str) or not topic.strip():
                raise ValueError("event_topic needs definition.topic = a non-empty topic string")
        elif self.kind == "prompt_rubric":
            prompt = d.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("prompt_rubric needs definition.prompt = a non-empty scoring prompt")
        return self

    @property
    def metric(self) -> str:
        """The alt_data metric name the series is stored under (idx_<id>) — what a strategy keys off."""
        return f"idx_{self.id}"

    @property
    def market_wide(self) -> bool:
        """A market-wide index is one series under symbol 'MARKET'; otherwise one series per entity."""
        return len(self.entities) == 0

    @property
    def is_social(self) -> bool:
        return self.kind in ("single_account", "social_bucket")

    @property
    def is_text(self) -> bool:
        return self.kind in ("event_topic", "prompt_rubric")

    @property
    def handles(self) -> list[str]:
        return [h for h in self.definition.get("handles", []) if isinstance(h, str)]

    def symbols(self) -> list[str]:
        """The store symbol keys this index writes (['MARKET'] when market-wide, else one per entity)."""
        return ["MARKET"] if self.market_wide else list(self.entities)
