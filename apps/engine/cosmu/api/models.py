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
    requires_confirm: bool = False
    reason: str | None = None


class LiveCaps(BaseModel):
    per_strategy_cap: float
    global_cap: float
    max_daily_loss: float


class EligibleStrategy(BaseModel):
    version_id: str
    name: str


class ActivateRequest(BaseModel):
    per_strategy_cap: float
    global_cap: float
    max_daily_loss: float
    confirm: bool


class ActivateResponse(BaseModel):
    armed: bool
    caps: LiveCaps
    eligible: list[EligibleStrategy]
    reason: str | None = None


class DefundRequest(BaseModel):
    scope: Literal["all", "strategy"]
    version_id: str | None = None


class DefundResponse(BaseModel):
    ok: bool
    defunded: list[str]


class LivePosition(BaseModel):
    instrument_id: str
    symbol: str
    qty: float
    avg_price: float
    unrealized_pnl: float
    venue: str


class LivePositionsResponse(BaseModel):
    armed: bool
    mode: Literal["testnet", "live", "paper"]
    daily_loss: float
    caps: LiveCaps
    positions: list[LivePosition]


class VenueState(BaseModel):
    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    enabled: bool  # the venue's own tick (remembered even when its class is off)
    effective: bool  # enabled AND the asset class is active — what actually trades
    has_data: bool


class AssetClassState(BaseModel):
    kind: Literal["crypto", "equity", "prediction"]
    label: str
    active: bool  # the class gate tick
    enabled: bool  # effective: active AND at least one venue ticked
    has_data: bool


class UniverseResponse(BaseModel):
    venues: list[VenueState]
    asset_classes: list[AssetClassState]


class VenueToggleRequest(BaseModel):
    venue_id: str
    enabled: bool


class ClassToggleRequest(BaseModel):
    kind: str
    active: bool


class GateVerdictResponse(BaseModel):
    decision: str  # "PASS" | "STOP"
    passed: bool
    best_signal: str
    deflated_sharpe_prob: float
    cscv_pbo: float
    buy_and_hold_return: float
    best_return: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    attempts: int
    reasons: list[str]
    bar: dict[str, Any]
    data_source: str  # "synthetic" until live LunarCrush + bars are wired
    ts: str


class GateStatusResponse(BaseModel):
    verdict: GateVerdictResponse | None
    preregistered_bar: dict[str, Any]


class DropOneSource(BaseModel):
    source: str
    sharpe_without: float
    delta: float


class DropOneClass(BaseModel):
    asset_class: str
    sharpe_without: float
    delta: float


class CrossAssetVerdict(BaseModel):
    """The four-arm cross-asset ablation verdict — shared snake_case contract used by the UI gate run.
    Mirrors cosmu.research.gate.CrossAssetVerdict exactly so the dataclass maps field-for-field."""

    decision: Literal["PASS", "STOP-narrow"]
    passed: bool
    price_only_return: float
    single_alt_return: float
    xasset_return: float
    buy_and_hold_return: float
    xasset_dsr: float
    single_alt_dsr: float
    cscv_pbo: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    attempts: int
    drop_one_source: list[DropOneSource]
    drop_one_class: list[DropOneClass]
    reasons: list[str]
    bar: dict[str, Any]
    data_source: Literal["live", "synthetic"]


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


# ---- Strategy Finder (grid-search → screen → Gate + profit_factor → WFO/holdout → config library) ----


class FinderRunRequest(BaseModel):
    max_variants: int | None = None
    seed_real: bool = False  # persist real backtested strategies to the configured store (bootstrap)


class FinderVariant(BaseModel):
    config_tag: str
    version_id: str | None
    profit_factor: float        # DISPLAYED secondary metric
    deflated_sharpe: float      # the ranking metric
    net_profit: float
    num_trades: int
    gate_passed: bool
    promoted: bool
    holdout_passed: bool


class FinderResponse(BaseModel):
    strategy_name: str
    grid_size: int
    screened: int
    gate_passed: int
    promoted: int
    leaderboard: list[FinderVariant]
    survivors: list[FinderVariant]


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


# ---- self-improvement flywheel: distilled skills + long-term memory insights ----


class Skill(BaseModel):
    """A reusable, parameterized SKILL recipe the Curator distilled from a gate-passing Version. `grade` is the
    downstream OOS pass-rate of Versions derived from it (the deterministic Gate's verdicts — never the Curator's)."""

    name: str
    grade: float
    success_count: int
    lineage: str
    recipe_summary: str
    created_at: str


class SkillsResponse(BaseModel):
    skills: list[Skill]


class MemoryInsight(BaseModel):
    """One thing the brain has LEARNED from long-term memory: a dead-end structure to avoid or a winning pattern
    to reuse. `ref` is the source Version id."""

    kind: Literal["dead_end", "winner_pattern"]
    text: str
    ref: str


class MemoryInsightsResponse(BaseModel):
    insights: list[MemoryInsight]


# ---- autonomy: the human-overseen master tick (engine builds, web consumes) ----


class TickSummary(BaseModel):
    authored: int
    gated_passed: int
    funded: int
    recommendations: int


class AutonomyStatusResponse(BaseModel):
    """The human-overview snapshot of the autonomous master tick. `running` = armed (not paused); the loop is
    cron-driven (one tick per call), so there is no 24/7 daemon. `live_enabled` is reported but the tick never
    arms live — money-adjacent stays gated."""

    running: bool
    paused: bool
    live_enabled: bool
    cycles_run: int
    last_tick_at: str | None
    last_action: str
    next_action: str
    last_summary: TickSummary


class AutonomyPauseResponse(BaseModel):
    paused: bool


class AutonomyTickResponse(BaseModel):
    authored: int
    gated_passed: int
    funded: int
    recommendations: int


class RecommendationActionResponse(BaseModel):
    ok: bool
    applied: bool = False
    reason: str | None = None


# ---- cost transparency: opex vs alpha (engine builds, web consumes) ----


class CostByCategory(BaseModel):
    category: str
    amount: float


class CostPerStrategy(BaseModel):
    version_id: str
    name: str
    opex: float
    net: float


class CostsResponse(BaseModel):
    total_usd: float
    by_category: list[CostByCategory]
    opex_vs_alpha: float
    per_strategy: list[CostPerStrategy]


# ---- alpha-decay: edge half-life + live-vs-funded drift (master/drift; web consumes) ----


class DriftSleeve(BaseModel):
    """One funded sleeve's alpha-decay snapshot. `defund` is the anticipatory verdict (pull capital BEFORE P&L
    turns); `half_life` is the estimated periods for the realized edge to halve (null = not decaying); `z`/`cusum`
    measure how far live has drifted below the edge it was funded on (`reference`)."""

    version_id: str
    defund: bool
    reason: str
    half_life: float | None
    periods_to_zero: float | None
    realized_edge: float
    reference_edge: float
    reference: str
    z: float
    cusum: float
    n: int


class DriftResponse(BaseModel):
    sleeves: list[DriftSleeve]

