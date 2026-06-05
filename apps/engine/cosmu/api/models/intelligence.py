from __future__ import annotations

from pydantic import BaseModel

# ---- system intelligence: "is the machine getting smarter?" (api/intelligence.py builds) ----


class FunnelStats(BaseModel):
    authored: int
    screened: int
    gate_passed: int
    funded: int
    live: int
    killed: int


class GateEfficiency(BaseModel):
    current: float
    trend: list[float]
    improving: bool


class MemoryDepth(BaseModel):
    dead_ends: int
    winners: int
    skills: int
    total: int


class RegimeCell(BaseModel):
    regime: str
    trend: str
    vol: str
    strategies: int


class RegimeCoverage(BaseModel):
    grid: list[RegimeCell]
    covered: int
    total: int
    by_label: dict[str, int]


class DataSource(BaseModel):
    source: str
    last_at: str | None
    points: int


class TickDetail(BaseModel):
    authored: int
    passed: int
    funded: int


class TickStats(BaseModel):
    total: int
    last_at: str | None
    avg_survivors_per_tick: float
    total_authored: int
    total_survivors: int
    recent: list[TickDetail]


class LineageEntry(BaseModel):
    origin: str | None = None
    operator: str | None = None
    total: int
    passed: int
    rate: float


class LineageStats(BaseModel):
    by_origin: list[LineageEntry]
    by_operator: list[LineageEntry]


class IntelligenceResponse(BaseModel):
    funnel: FunnelStats
    gate_efficiency: GateEfficiency
    memory: MemoryDepth
    regime_coverage: RegimeCoverage
    data_freshness: list[DataSource]
    ticks: TickStats
    lineage: LineageStats
