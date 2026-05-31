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

