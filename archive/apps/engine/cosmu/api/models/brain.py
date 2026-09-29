from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- research brain snapshot (the live ML phase) ----


class BrainGated(BaseModel):
    generated: int
    passed: int
    killed: int
    kill_rate: float


class BrainSurvivor(BaseModel):
    version_id: str
    name: str
    net_pct: float
    survival_score: float


class BrainGraveyard(BaseModel):
    name: str
    reasons: list[str]


class BrainSource(BaseModel):
    name: str
    kind: str
    low_confidence: bool


class BrainRegime(BaseModel):
    label: str
    vol_bucket: str
    trend: str


class BrainRanking(BaseModel):
    version_id: str
    name: str
    score: float
    trained: bool


class BrainResponse(BaseModel):
    """The live brain snapshot the web app reads: LLM on/off, the latest research pass's gated counts +
    survivors + graveyard, the propose-only sources/tools, the current market regime, and the survival
    model's validation-queue ranking (ordering only — never a veto)."""

    llm: Literal["on", "off"]
    gated: BrainGated
    survivors: list[BrainSurvivor]
    graveyard: list[BrainGraveyard]
    sources: list[BrainSource]
    tools: list[str]
    regime: BrainRegime
    survival_ranking: list[BrainRanking]
