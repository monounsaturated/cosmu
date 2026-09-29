# intent: API contracts for the INDEX surface (the /indexes page + detail). inputs: registry/compute/monitor
# reads; outputs: stable Pydantic response models the generated TS consumes; invariants: frontend never
# hand-types these; `available` carries the honest "registry not active yet" state; every number is real or null.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# The authorable spec IS the POST body — one definition, no drift (re-exported for the models barrel).
from cosmu.indexes.spec import IndexSpec  # noqa: F401


class IndexHealthModel(BaseModel):
    """Freshness + ranking-stability readout for one index (deterministic; honest empties)."""

    n_points: int
    latest_value: float | None
    latest_at: str | None
    staleness_hours: float | None
    freshness: str          # "fresh" | "stale" | "never"
    stability: float | None  # stdev of recent values; lower = steadier ranking
    reliability: str        # "stable" | "moderate" | "volatile" | "untested"
    transform_version: str


class IndexCard(BaseModel):
    """One row on the Indexes table — the definition at a glance + its current value/health."""

    id: str
    name: str
    rationale: str
    kind: str
    definition: dict[str, Any]
    status: str
    market_wide: bool
    metric: str
    entities: list[str]
    cadence_minutes: int
    created_at: str | None
    health: IndexHealthModel
    n_strategies_using: int


class IndexSeriesPoint(BaseModel):
    ts: str
    value: float


class IndexSeries(BaseModel):
    """One stored symbol's point-in-time series (symbol='MARKET' for a market-wide index)."""

    symbol: str
    points: list[IndexSeriesPoint]


class IndexStrategyRef(BaseModel):
    version_id: str
    name: str
    status: str


class IndexDetail(BaseModel):
    """Full index view: definition + health + the stored series + strategies built on it."""

    available: bool
    index: IndexCard | None
    series: list[IndexSeries]
    strategies_using: list[IndexStrategyRef]


class IndexesResponse(BaseModel):
    available: bool
    indexes: list[IndexCard]


class IndexDefineResponse(BaseModel):
    ok: bool
    available: bool
    index: IndexCard | None
    error: str | None = None
