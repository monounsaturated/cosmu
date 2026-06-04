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


class TakeProfitLeg(BaseModel):
    """One partial-exit leg of a multi-TP exit. `at` is the take-profit distance (a ParamRef, fit from the
    space — no magic numbers); `size_pct` is the FRACTION of the open position closed at this leg (also a
    ParamRef). Legs fill in ascending `at` order; the runner carries whatever fraction is left over."""

    at: ParamRef
    size_pct: ParamRef


class ExitPlan(BaseModel):
    """Composable, optimizer-fittable exit structure layered on top of the single stop/take. All thresholds are
    ParamRefs so the Finder/optimizer fits them — never hardcoded. None on a leaf => that behaviour is off."""

    # Partial exits: take profit in N legs (each a fraction of the position) instead of one all-or-nothing TP.
    multi_tp: list[TakeProfitLeg] = Field(default_factory=list)
    # Move the stop to break-even (entry) once the first TP leg has filled — frees the runner to ride risk-free.
    break_even_after_tp1: bool = False
    # The runner's trailing-stop distance once break-even is armed (asymmetric: tight stop, open-ended upside).
    runner_trail: ParamRef | None = None


class ExitRules(BaseModel):
    stop_loss: ParamRef
    take_profit: ParamRef
    signal_exits: list[Condition] = Field(default_factory=list)
    time_stop_days: ParamRef | None = None
    plan: ExitPlan | None = None


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


class MaTrendFilter(BaseModel):
    """Long-only regime filter: only allow entries when price is above its moving average (spot, long-only).
    `ma_lookback` is a ParamRef so the MA window is fit, not hardcoded."""

    ma_lookback: ParamRef


class OpeningRangeBreakout(BaseModel):
    """Upside-only opening-range breakout. `range_bars` defines the range window (a ParamRef); `anchor`
    chooses a fixed session anchor (the first N bars of each window) vs a rolling window. Entry fires when
    price breaks ABOVE the range high (long-only). `buffer` is a ParamRef break-above margin (no magic numbers)."""

    range_bars: ParamRef
    buffer: ParamRef
    anchor: Literal["session", "rolling"] = "rolling"


class FairValueGap(BaseModel):
    """Upside fair-value-gap (FVG) retest setup. A bullish FVG is a 3-bar imbalance (bar[i-2].high < bar[i].low).
    Entry fires when price RETESTS the gap from above. `max_retests` (a ParamRef) caps how many times the same
    gap may be re-entered (fvg_multiple); `gap_min` is the minimum gap size as a ParamRef fraction (no magic
    numbers). Long/upside-only."""

    max_retests: ParamRef
    gap_min: ParamRef


class EntrySetup(BaseModel):
    """Composable, optimizer-fittable entry structure layered alongside `entry` conditions. Each leaf is
    optional (None => off). All setups are long/upside-only (spot). Thresholds are ParamRefs — fit, never magic."""

    ma_trend_filter: MaTrendFilter | None = None
    orb: OpeningRangeBreakout | None = None
    fvg: FairValueGap | None = None


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
    setup: EntrySetup | None = None
    # Trade side: +1 = long (the spot/upside-only default — existing specs are unchanged), -1 = short (the
    # perp/short leg; entry conditions fire a short, stop is ABOVE entry, take-profit BELOW), 0 = the signal
    # decides per bar (reserved; treated as long until per-bar direction signals land). Entry CONDITIONS are
    # unchanged — `direction` only flips which way the resulting position is taken, so the long-only assumption
    # baked into the backtest is lifted without rewriting any condition logic.
    direction: Literal[-1, 0, 1] = 1
    # Funding rate (perp carry) accrues to the open position as P&L each bar when set. The value names the
    # alt-data feature carrying the point-in-time periodic funding rate (e.g. "funding_rate"); None => no
    # funding leg (spot — exactly the prior behaviour). A long pays funding when the rate is positive; a short
    # receives it. No magic numbers: the rate comes from the PIT alt-data join, not a constant.
    funding_feature: str | None = None

