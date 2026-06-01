# intent: define Pydantic API contracts consumed by generated TS; inputs: engine/store rows; outputs: stable response models; invariants: frontend never hand-types server contracts.

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class Point(BaseModel):
    ts: str
    value: float


class Allocation(BaseModel):
    strategy_id: str
    name: str
    weight: float
    capital: float
    venue: str


class CostSlice(BaseModel):
    category: str
    amount: float


class PortfolioResponse(BaseModel):
    equity_curve: list[Point]
    pnl_net: float
    allocation: list[Allocation]
    costs: list[CostSlice]
    live_enabled: bool
    opex_vs_alpha: float


class LeaderboardRow(BaseModel):
    version_id: str
    name: str
    sleeve_return_pct: float
    deflated_sharpe: float
    net_pct: float
    pbo: float
    status: str
    lineage: str


class LeaderboardResponse(BaseModel):
    rows: list[LeaderboardRow]


class Execution(BaseModel):
    id: str
    side: str
    qty: float
    price: float
    fee: float
    venue: str | None
    ts: str


class Backtest(BaseModel):
    id: str
    kind: str
    oos_return: float
    deflated_sharpe: float
    max_dd: float
    win_rate: float
    num_trades: int
    pbo: float
    passed_gates: bool


class StrategyDetailResponse(BaseModel):
    version_id: str
    name: str
    spec: dict[str, Any]
    generated_code: str
    params: dict[str, Any]
    trades: list[Execution]
    backtests: list[Backtest]
    notes_md: str
    holdout: dict[str, Any]


class CommandRequest(BaseModel):
    text: str


class CommandResponse(BaseModel):
    parsed_policy: dict[str, Any]
    applied: bool
    reply_md: str


class Recommendation(BaseModel):
    id: str
    ts: str
    kind: str
    body: str
    state: Literal["open", "approved", "dismissed"]
    payload: dict[str, Any]


class RecommendationsResponse(BaseModel):
    items: list[Recommendation]


class ToggleRequest(BaseModel):
    enabled: bool
    confirm: bool


class ToggleResponse(BaseModel):
    enabled: bool
    promoted: list[str]
    caps: dict[str, float]


class VenueState(BaseModel):
    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    enabled: bool
    has_data: bool


class AssetClassState(BaseModel):
    kind: Literal["crypto", "equity", "prediction"]
    label: str
    enabled: bool
    has_data: bool


class UniverseResponse(BaseModel):
    venues: list[VenueState]
    asset_classes: list[AssetClassState]


class VenueToggleRequest(BaseModel):
    venue_id: str
    enabled: bool


class Event(BaseModel):
    id: int
    ts: str
    actor: str
    kind: str
    ref_type: str | None
    ref_id: str | None
    payload: dict[str, Any]


class EventsResponse(BaseModel):
    events: list[Event]


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
    paper: int
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


# ---- chat strategy authoring ----


class AuthorRequest(BaseModel):
    brief: str
    features: list[str] | None = None
    venues: list[str] | None = None


class AuthorResponse(BaseModel):
    name: str
    rationale: str
    base_template: str
    features: list[str]
    data_sources: list[str]
    venues: list[str]
    valid: bool
    issues: list[str]
    requires_approval: bool
    guardrails: list[str]
    notes: list[str]
    spec: dict[str, Any]


class AuthorRunRequest(BaseModel):
    brief: str
    features: list[str] | None = None
    venues: list[str] | None = None
    cohort_size: int | None = None

