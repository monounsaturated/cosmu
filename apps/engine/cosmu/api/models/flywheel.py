from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- self-improvement flywheel: distilled skills + long-term memory insights ----


class Skill(BaseModel):
    """A reusable, parameterized SKILL recipe the Curator distilled from a gate-passing Version. `grade` is the
    downstream OOS pass-rate of Versions derived from it (the deterministic Gate's verdicts — never the Curator's)."""

    name: str
    grade: float
    success_count: int
    lineage: str
    recipe_summary: str
    created_at: str


class SkillsResponse(BaseModel):
    skills: list[Skill]


class MemoryInsight(BaseModel):
    """One thing the brain has LEARNED from long-term memory: a dead-end structure to avoid or a winning pattern
    to reuse. `ref` is the source Version id."""

    kind: Literal["dead_end", "winner_pattern"]
    text: str
    ref: str


class MemoryInsightsResponse(BaseModel):
    insights: list[MemoryInsight]
