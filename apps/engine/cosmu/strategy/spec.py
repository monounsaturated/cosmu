# intent: define the typed hypothesis format authored by the lab agent; inputs: validated LLM output; outputs: StrategySpec; invariants: no entry/exit magic numbers and final sizing remains with the deterministic master.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParamSpace(BaseModel):
    kind: Literal["int", "float", "choice"]
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    choices: list[float] | None = None


class ParamRef(BaseModel):
    param: str


class FeatureRef(BaseModel):
    name: str
    lookback: ParamRef | int | None = None


class Condition(BaseModel):
    feature: FeatureRef
    op: Literal["gt", "gte", "lt", "lte", "cross_up", "cross_down", "between"]
    threshold: ParamRef


class ExitRules(BaseModel):
    stop_loss: ParamRef
    take_profit: ParamRef
    signal_exits: list[Condition] = Field(default_factory=list)
    time_stop_days: ParamRef | None = None


class UniverseSelector(BaseModel):
    venues: list[str]
    asset_classes: list[Literal["crypto", "equity", "fx", "prediction"]]
    min_liquidity_usd: float = 1_000_000
    min_instruments: int = 5


class Horizon(BaseModel):
    bar_size: Literal["1h", "4h", "1d"]
    min_hold_days: int
    max_hold_days: int


class RiskRules(BaseModel):
    max_concurrent_positions: int = 3
    max_position_pct: float = 0.05
    conviction: float = 0.5


class StrategySpec(BaseModel):
    name: str
    rationale: str
    universe: UniverseSelector
    horizon: Horizon
    catalyst: str | None = None
    entry: list[Condition]
    exit: ExitRules
    risk: RiskRules
    param_space: dict[str, ParamSpace]

