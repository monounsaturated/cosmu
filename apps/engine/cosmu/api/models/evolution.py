from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# ---- autonomous evolution loop ----


class CohortRunRequest(BaseModel):
    cohort_size: int | None = None
    explore_pct: float | None = None
    seed: int | None = None
    pine_scripts: list[str] | None = None


class EvaluatedStrategy(BaseModel):
    version_id: str
    name: str
    origin: str
    lane: str
    deflated_sharpe: float
    oos_return_pct: float
    passed: bool
    reasons: list[str]


class CohortSummaryResponse(BaseModel):
    cohort_id: str
    seed: int
    generated: int
    invalid: int
    killed: int
    passed: int
    kill_rate: float
    lanes: dict[str, int]
    pine_imported: int
    survivors: list[EvaluatedStrategy]
    graveyard: list[EvaluatedStrategy]
    pine_notes: list[str]


class GraveyardRow(BaseModel):
    version_id: str
    name: str
    origin: str
    kill_reason: str
    deflated_sharpe: float


class PopulationResponse(BaseModel):
    total: int
    forward_test: int   # forward-test + live (everything past the gate, funded)
    live: int           # of which armed on real capital
    killed: int
    by_origin: dict[str, int]
    by_lane: dict[str, int]
    kill_rate: float
    graveyard: list[GraveyardRow]


class PineTranslateRequest(BaseModel):
    source: str


class PineTranslateResponse(BaseModel):
    name: str
    param_count: int
    indicators: list[str]
    conditions: list[str]
    notes: list[str]
    lifted_params: dict[str, float]
    spec: dict[str, Any]


class PineSample(BaseModel):
    name: str
    source: str


class PineSamplesResponse(BaseModel):
    samples: list[PineSample]
