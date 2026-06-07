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


class MetaLabel(BaseModel):
    """Triple-barrier meta-labeling (López de Prado). A SECONDARY regularized-logistic classifier predicts
    P(the primary signal's trade is a net winner) from `features` read point-in-time at entry, and gates the
    primary trade: SKIP it below `prob_threshold`, otherwise take it (optionally SIZING the notional by the
    predicted probability). It only SIZES or SKIPS — it NEVER changes `direction` (the primary signal owns the
    side). The training label for each past primary event is which of the three barriers (stop-loss /
    take-profit / time) the trade hit first, netted of round-trip cost (win=1, else 0) — the same stop/take/
    time that `ExitRules` already carries. Training is EXPANDING-WINDOW and point-in-time: at each entry only
    primary events whose barrier RESOLVED on a strictly earlier bar feed the fit, so the secondary model never
    sees its own trade's outcome (no look-ahead). Until META_MIN_TRAIN resolved events exist the trade is
    ungated (the bare primary book), so the gate can only ever subtract trades the primary would have taken.
    None on the spec => no meta-label at all (the primary book, byte-identical to the prior behaviour).

    The secondary model is a logistic on purpose: spot history is <100k rows, far too thin for a boosted tree
    to do anything but overfit (LightGBM is reserved for offline MDA feature-importance, never the live gate).
    The `features` are FeatureRefs so each names a real registry feature with its own fitted lookback (no magic
    numbers); `funding_rate` is the canonical one to include. `prob_threshold` is a ParamRef so the size/skip
    cut is fit from the param space by the Finder/Gate like every other knob — never hardcoded."""

    features: list[FeatureRef]
    prob_threshold: ParamRef
    # "skip": binary gate (take at full size iff p >= threshold). "proportional": also scale the notional by the
    # predicted win probability above the threshold (conviction sizing). Both only size/skip — never flip side.
    sizing: Literal["skip", "proportional"] = "skip"


class StrategySpec(BaseModel):
    name: str
    rationale: str
    # Evaluation lane — the TYPED discriminator the master uses to pick the correct evaluator path, so routing is
    # explicit on the spec instead of an accident of which function a runner happens to call (the silent mis-routing
    # that killed long-only equity in the gate-lane). "gate" = a NOVEL in-sample-mined hypothesis: judged by the
    # honest 0.95 deflated-Sharpe bar + BH-FDR cohort gate (promote_cohort). "deploy" = an externally-documented
    # strategy with decades of OOS/live evidence: judged by the positive-OOS deployment bar (taa.validate-style),
    # NOT the 0.95 in-sample Gate. Default "gate" preserves ALL current behaviour — every existing spec is gate-lane.
    lane: Literal["gate", "deploy"] = "gate"
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
    # Triple-barrier meta-labeling: a secondary logistic gate that SIZES/SKIPS the primary trade by its predicted
    # win probability (never flips direction). None => no meta-label, byte-identical to the prior behaviour. See
    # MetaLabel for the full point-in-time / no-look-ahead contract.
    meta_label: MetaLabel | None = None

