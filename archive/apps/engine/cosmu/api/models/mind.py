from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from cosmu.api.models.flywheel import MemoryInsight
from cosmu.api.models.intelligence import RegimeCell

# ---- Mind: the agent's standardized self-knowledge — what it KNOWS, how it THINKS, what it has LEARNED. ----
# A reasoning surface only: the analyst panel debates a market read, but it never funds or fires (railguard).


class MindStance(BaseModel):
    """One perspective's read in the analyst panel. `kind` separates MARKET analysts (vote on the consensus)
    from PROCESS analysts (ML + memory — they report the machine's self-knowledge). `lean` is abstain when the
    feed is not ingested yet (honest, never fabricated)."""

    perspective: str
    kind: Literal["market", "process"]
    lean: Literal["bullish", "bearish", "neutral", "abstain"]
    conviction: float  # this IS the verdict's confidence (0..1)
    weight: float
    headline: str
    rationale: str
    evidence: list[str]
    as_of: str | None = None
    low_confidence: bool = False
    # The typed verdict's audit fields: `score` is the signed directional strength (-1..1); `source` is the
    # verdict's provenance ("heuristic" = deterministic, "llm" = a rubric-scored model verdict, "abstain" = no
    # data); `rubric` names the rubric a market pillar was scored under. The LLM only scores — the gate disposes.
    score: float = 0.0
    source: Literal["heuristic", "llm", "abstain"] = "heuristic"
    rubric: str | None = None


class MindSourceItem(BaseModel):
    """One data source the agent can read, with whether it is ingested + when. `value` is the latest
    point-in-time reading (None when not ingested yet)."""

    name: str
    source: str
    tier: str
    prior: str
    ingested: bool
    last_at: str | None = None
    value: float | None = None
    low_confidence: bool = False


class MindLens(BaseModel):
    """The sources for one perspective (e.g. Macro), grouped so 'what it knows' lines up with 'how it thinks'."""

    perspective: str
    ingested: int
    total: int
    items: list[MindSourceItem]


class MindLearnings(BaseModel):
    """What the agent has LEARNED: long-term memory, the ML survival model's state, regime coverage, and whether
    the gate pass-rate is improving."""

    insights: list[MemoryInsight]
    ml_trained: bool
    ml_backend: str
    ml_auroc: float | None = None
    ml_labels: int
    dead_ends: int
    winners: int
    skills: int
    gate_rate: float
    gate_trend: list[float]
    gate_improving: bool
    regime_grid: list[RegimeCell]
    regime_covered: int
    regime_total: int


class MindAuditContribution(BaseModel):
    """One voting pillar's contribution to the consensus tally — exposed so the aggregation is replayable.
    `contribution` = `weight` × `conviction` (the LLM scores each pillar; this combination is pure math)."""

    perspective: str
    lean: str
    weight: float
    conviction: float
    source: str
    contribution: float


class MindConsensusAudit(BaseModel):
    """The deterministic, auditable aggregation laid bare: the rule, the per-lean tally, and the per-pillar
    contributions that sum to it. No LLM and no money on this path — the committee's vote is just math."""

    method: str
    tally: dict[str, float]
    total: float
    consensus: str
    contributions: list[MindAuditContribution]


class MindResponse(BaseModel):
    """The full Mind snapshot. `railguard` restates the hard rule shown wherever the Mind appears: it reasons,
    it never moves money. `consensus`/`conviction`/`agreement` summarize the debate over the MARKET analysts."""

    as_of: str | None = None
    railguard: str
    consensus: Literal["bullish", "bearish", "neutral"]
    conviction: float
    agreement: float
    contested: bool
    narrative: str
    stances: list[MindStance]
    bull_case: list[str]
    bear_case: list[str]
    consensus_audit: MindConsensusAudit | None = None
    knows: list[MindLens]
    learnings: MindLearnings
