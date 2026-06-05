from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# ---- ML-through-natural-language seam (LLM proposes the task; the deterministic scorer judges) ----


class MlRequest(BaseModel):
    request: str
    limit: int | None = None


class MlRankedItem(BaseModel):
    version_id: str
    name: str
    score: float            # edge-persistence in [0,1] — ordering only, never a gate input
    gate_passed: bool       # the DETERMINISTIC gate verdict, reported (judged) — never altered by the ML
    deflated_sharpe: float


class MlFeatureWeight(BaseModel):
    feature: str
    weight: float


class MlResponse(BaseModel):
    task: Literal["survival_ranking", "feature_importance"]
    request: str
    llm: str
    trained: bool
    backend: str
    n_labels: int
    ranking: list[MlRankedItem]
    feature_importance: list[MlFeatureWeight]
    notes: list[str]
