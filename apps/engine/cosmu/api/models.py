# intent: define Pydantic API contracts consumed by generated TS; inputs: engine/store rows; outputs: stable response models; invariants: frontend never hand-types server contracts.

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class Point(BaseModel):
    ts: str
    value: float


class CostSlice(BaseModel):
    category: str
    amount: float


class OverviewResponse(BaseModel):
    """The aggregate read-out for the Overview surface ("are we making money?"): the Σ of all standalone
    forward-test tracks. This is a pure read-out — there is NO pooled wallet and no cross-track allocation."""

    equity_curve: list[Point]
    pnl_net: float
    costs: list[CostSlice]
    live_enabled: bool
    opex_vs_alpha: float


class LeaderboardRow(BaseModel):
    version_id: str
    name: str
    track_return_pct: float
    deflated_sharpe: float
    net_pct: float
    pbo: float
    status: str
    lineage: str
    # ADVISORY forward-test maturity signal (master/forward_maturity.py) — SURFACED, NOT ENFORCED. `forward_age_days`
    # is calendar time the track's forward-test clock has run since its first mark; `live_ready` recommends a track
    # that has both matured (>= FORWARD_TEST_MIN_DAYS) and is net-of-fee positive. The operator launches via the
    # modal at their discretion; the 5 interlocks remain the only hard gate. Never consulted by the gate/money path.
    forward_age_days: float
    live_ready: bool
    # Faceted taxonomy (cosmu/strategy/taxonomy.py), all DERIVED from the spec — never hand-tagged. The
    # Strategies surface filters on these real fields. `signal_family` is the primary filter (from the
    # named features the spec references); the rest are orthogonal facets.
    signal_family: str
    signal_family_label: str
    features: list[str]
    asset_class: str
    venue: str
    timeframe: str
    origin: str
    edge_type: str


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
    mode: Literal["testnet", "live", "sim"]
    daily_loss: float
    caps: LiveCaps
    positions: list[LivePosition]


class LiveVenue(BaseModel):
    """One venue on the LIVE surface: is it legal to trade here from our jurisdiction, are execution keys
    wired (connected), is it ticked into the universe, and how much real capital is deployed there now."""

    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    live_legal: bool      # legal/available to move real money from our jurisdiction (catalog fact)
    connected: bool       # execution credentials wired for this venue (else "not connected")
    enabled: bool         # ticked into the trading universe
    deployed_usd: float   # real capital at risk here right now (sum of live positions' notional)


class LiveVenuesResponse(BaseModel):
    jurisdiction: str
    global_cap: float            # the total live budget across all venues
    total_deployed_usd: float
    venues: list[LiveVenue]


class VenueFeeTierInfo(BaseModel):
    """One 30d-volume fee tier — read-only display data for the launch modal."""

    min_volume_30d_usd: float
    maker_fee_bps: float
    taker_fee_bps: float


class VenueFeeInfo(BaseModel):
    """Fees + key-gating state for one venue — the read-only feed for the launch modal.
    `configured` is True iff this venue's API keys are present in the server env. The keys are
    NEVER returned — only the boolean. A venue whose `configured` is False must be greyed-out in
    the UI; it cannot arm regardless of the live toggle."""

    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    maker_fee_bps: float
    taker_fee_bps: float
    min_notional: float
    fee_tiers: list[VenueFeeTierInfo]
    configured: bool    # True = API keys are in Railway env; False = venue inert, grey-out in UI
    live_enabled: bool  # whether the venue has a real-money execution adapter at all


class VenueInstrumentInfo(BaseModel):
    """Minimal instrument info for the launch modal asset picker."""

    id: str
    venue_id: str
    symbol: str
    asset_class: Literal["crypto", "equity", "prediction"]
    min_notional: float


class VenueCatalogResponse(BaseModel):
    """Read-only catalog for the launch modal: venues with fees + key-gating, and instruments.
    GET-only — no mutation, no key values, just the facts the UI needs to render the modal."""

    venues: list[VenueFeeInfo]
    instruments: list[VenueInstrumentInfo]


class LaunchActivateRequest(BaseModel):
    """Request body for the strategy launch-live flow: arm one strategy on a specific venue + asset
    with a given budget. Confirm must be true (two-click safety); caps are set here and carried
    through to the live_caps upsert so the operator sees exactly what they agreed to.
    `override_forward_test` (default OFF) is the explicit human escape hatch: arm a strategy that has NOT
    yet cleared the >= FORWARD_TEST_MIN_DAYS net-positive forward-test precondition, recorded with a loud
    `live_override_launch` warning event. It never waives the regime gate or the 5 execution interlocks."""

    version_id: str
    venue_id: str
    symbol: str
    budget: float = 100.0
    per_strategy_cap: float = 100.0
    global_cap: float = 1000.0
    max_daily_loss: float = 50.0
    confirm: bool
    override_forward_test: bool = False


class LaunchActivateResponse(BaseModel):
    """Result of the launch-live flow for one strategy.
    `armed` = eligibility + the 5 interlocks cleared and the strategy is now live (status='live' written here).
    `forward_test_days` = forward-test maturity in days (None = no track yet).
    `readiness` = "proven" (>= FORWARD_TEST_MIN_DAYS forward days net-positive) or "not yet proven". This is now
    a HARD precondition for arming, not merely advisory: a "not yet proven" strategy is refused (armed=False)
    unless the human sets `override_forward_test`.
    `overridden` = True when the human waived the forward-test precondition to arm an unproven strategy."""

    armed: bool
    version_id: str
    venue_id: str
    symbol: str
    budget: float
    caps: LiveCaps
    eligible: list[EligibleStrategy]
    forward_test_days: float | None = None   # how many real forward-test days this track has (None = no track)
    readiness: Literal["proven", "not yet proven"] = "not yet proven"
    overridden: bool = False                 # True when arming waived the forward-test precondition (logged)
    reason: str | None = None


class JurisdictionOption(BaseModel):
    code: str            # ISO-3166 alpha-2
    label: str
    legal_venue_ids: list[str]   # venues live-legal from here (drives the Live "available" set)


class JurisdictionsResponse(BaseModel):
    current: str
    options: list[JurisdictionOption]


class SetJurisdictionRequest(BaseModel):
    code: str


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


# ---- idea inbox (natural-language strategy intake) ----


class InboxIdeaRequest(BaseModel):
    text: str
    name: str | None = None


class InboxIdeaResponse(BaseModel):
    ok: bool
    filename: str
    name: str
    queued: int  # ideas still waiting for the next scan to turn them into gated specs
    note: str


class InboxQueueItem(BaseModel):
    filename: str
    name: str
    ts: str
    status: Literal["queued", "imported"]


class InboxQueueResponse(BaseModel):
    items: list[InboxQueueItem]
    inbox_dir: str


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


class AutonomyTickAcceptedResponse(BaseModel):
    job_id: str
    status: str  # always "running" on 202


class AutonomyTickJobResponse(BaseModel):
    job_id: str
    status: str  # "running" | "done" | "error"
    result: AutonomyTickResponse | None = None
    error: str | None = None


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


class InfraLine(BaseModel):
    """One static monthly infra cost line from MASTER_PLAN §9. amount is the midpoint estimate;
    amount_min/amount_max are the range. Source is the authoritative static seed — no billing API."""
    vendor: str
    category: str
    amount: float
    amount_min: float
    amount_max: float
    note: str


class LlmCallSummary(BaseModel):
    """Aggregated summary of recorded LLM calls. total_cost is $0 on :free OpenRouter models
    (accurate). call_count is the real number of rows recorded since the DB was seeded."""
    call_count: int
    total_cost: float
    by_task: dict[str, int]  # task -> call count


class VendorActual(BaseModel):
    """Live-fetched vendor spend for the current month vs its configured monthly budget cap.
    amount=0 for free/constant vendors; budget=0 means uncapped (no alert threshold set)."""
    vendor: str
    category: str
    amount: float
    budget: float   # 0 = uncapped
    period: str     # YYYY-MM


class CostsResponse(BaseModel):
    total_usd: float
    by_category: list[CostByCategory]
    opex_vs_alpha: float
    per_strategy: list[CostPerStrategy]
    infra_lines: list[InfraLine]
    llm_calls: LlmCallSummary
    vendor_actuals: list[VendorActual]


# ---- alpha-decay: edge half-life + live-vs-funded drift (master/drift; web consumes) ----


class DriftTrack(BaseModel):
    """One funded track's alpha-decay snapshot. `defund` is the anticipatory verdict (pull capital BEFORE P&L
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
    tracks: list[DriftTrack]


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


# ---- Mind: the agent's standardized self-knowledge — what it KNOWS, how it THINKS, what it has LEARNED. ----
# A reasoning surface only: the analyst panel debates a market read, but it never funds or fires (railguard).


class MindStance(BaseModel):
    """One perspective's read in the analyst panel. `kind` separates MARKET analysts (vote on the consensus)
    from PROCESS analysts (ML + memory — they report the machine's self-knowledge). `lean` is abstain when the
    feed is not ingested yet (honest, never fabricated)."""

    perspective: str
    kind: Literal["market", "process"]
    lean: Literal["bullish", "bearish", "neutral", "abstain"]
    conviction: float  # this IS the verdict's confidence (0..1)
    weight: float
    headline: str
    rationale: str
    evidence: list[str]
    as_of: str | None = None
    low_confidence: bool = False
    # The typed verdict's audit fields: `score` is the signed directional strength (-1..1); `source` is the
    # verdict's provenance ("heuristic" = deterministic, "llm" = a rubric-scored model verdict, "abstain" = no
    # data); `rubric` names the rubric a market pillar was scored under. The LLM only scores — the gate disposes.
    score: float = 0.0
    source: Literal["heuristic", "llm", "abstain"] = "heuristic"
    rubric: str | None = None


class MindSourceItem(BaseModel):
    """One data source the agent can read, with whether it is ingested + when. `value` is the latest
    point-in-time reading (None when not ingested yet)."""

    name: str
    source: str
    tier: str
    prior: str
    ingested: bool
    last_at: str | None = None
    value: float | None = None
    low_confidence: bool = False


class MindLens(BaseModel):
    """The sources for one perspective (e.g. Macro), grouped so 'what it knows' lines up with 'how it thinks'."""

    perspective: str
    ingested: int
    total: int
    items: list[MindSourceItem]


class MindLearnings(BaseModel):
    """What the agent has LEARNED: long-term memory, the ML survival model's state, regime coverage, and whether
    the gate pass-rate is improving."""

    insights: list[MemoryInsight]
    ml_trained: bool
    ml_backend: str
    ml_auroc: float | None = None
    ml_labels: int
    dead_ends: int
    winners: int
    skills: int
    gate_rate: float
    gate_trend: list[float]
    gate_improving: bool
    regime_grid: list[RegimeCell]
    regime_covered: int
    regime_total: int


class MindAuditContribution(BaseModel):
    """One voting pillar's contribution to the consensus tally — exposed so the aggregation is replayable.
    `contribution` = `weight` × `conviction` (the LLM scores each pillar; this combination is pure math)."""

    perspective: str
    lean: str
    weight: float
    conviction: float
    source: str
    contribution: float


class MindConsensusAudit(BaseModel):
    """The deterministic, auditable aggregation laid bare: the rule, the per-lean tally, and the per-pillar
    contributions that sum to it. No LLM and no money on this path — the committee's vote is just math."""

    method: str
    tally: dict[str, float]
    total: float
    consensus: str
    contributions: list[MindAuditContribution]


class MindResponse(BaseModel):
    """The full Mind snapshot. `railguard` restates the hard rule shown wherever the Mind appears: it reasons,
    it never moves money. `consensus`/`conviction`/`agreement` summarize the debate over the MARKET analysts."""

    as_of: str | None = None
    railguard: str
    consensus: Literal["bullish", "bearish", "neutral"]
    conviction: float
    agreement: float
    contested: bool
    narrative: str
    stances: list[MindStance]
    bull_case: list[str]
    bear_case: list[str]
    consensus_audit: MindConsensusAudit | None = None
    knows: list[MindLens]
    learnings: MindLearnings


# ---- Source-trust scoreboard: freshness × realized gate contribution per data source. ----
# Honest: abstains (trust_score=0, status="no data") when a source has no data ingested.
# Never fabricates; no LLM on this path. The gate/money path is deterministic and separate.


class SourceTrustRow(BaseModel):
    """Trust metadata for one data source in plain English.

    `source` is the registry source string (e.g. "alternative.me", "fred", "news").
    `features` is the list of feature names served by this source.
    `last_at` is the latest availability time across all metrics for this source (ISO-8601 UTC, or null).
    `freshness_label` is plain-language freshness, e.g. "fresh 4 h", "aging 3 d", "stale 10 d", "no data".
    `status` is the badge bucket: "fresh" | "recent" | "aging" | "stale" | "no data".
    `gate_pass_count` is the number of gate-passed backtests that used any feature from this source.
    `trust_score` is a normalized [0, 1] composite (freshness × gate contribution).
    `summary` is a one-liner in plain English for the scoreboard card.
    `tier` is "tier0" or "tier1" (tier0 = higher-confidence, tier1 = low-confidence until validated OOS).
    `hours_since` is hours since last fresh data (null when no data)."""

    source: str
    features: list[str]
    last_at: str | None = None
    freshness_label: str
    status: Literal["fresh", "recent", "aging", "stale", "no data"]
    gate_pass_count: int
    trust_score: float
    summary: str
    tier: str
    hours_since: float | None = None


class SourceTrustResponse(BaseModel):
    """The source-trust scoreboard: one row per registered data source, sorted best-first.
    Honest: a source with no data ingested yet shows trust_score=0, status="no data"."""

    as_of: str
    rows: list[SourceTrustRow]


# ---- Scores cockpit: per-source + composite INDEX scores grouped by category. ----
# Honest: a category/source with no ingested data reports connected=False and index_score=null (never a
# fabricated score). A key-gated source whose key is absent on the engine shows disabled=True so the UI
# greys it out. Reviews are DETERMINISTIC plain-language reads — never on the gate/scoring/money path.


class ScoreSourceRow(BaseModel):
    """One source inside a cockpit category.

    `connected` is True iff data has been ingested (status != "no data"). `key_required` marks a source
    that needs a provider key to return data; `key_present` is whether that key is set on the engine env;
    `disabled` = key_required AND NOT key_present (the UI greys it out). `review` is a plain-language read."""

    source: str
    category: str
    features: list[str]
    last_at: str | None = None
    freshness_label: str
    status: Literal["fresh", "recent", "aging", "stale", "no data"]
    trust_score: float
    tier: str
    hours_since: float | None = None
    connected: bool
    key_required: bool
    key_name: str | None = None
    key_present: bool
    disabled: bool
    review: str


class ScoreCategory(BaseModel):
    """A cockpit category (crypto · social · macro · OSINT · metals/forex) with a composite INDEX over the
    sources that actually have data. `index_score` is null when nothing is live (honest offline)."""

    key: str
    label: str
    index_score: float | None = None
    status: str  # "fresh" | "recent" | "aging" | "stale" | "no data" | "offline"
    freshness_label: str
    connected: bool
    live_sources: int
    total_sources: int
    review: str
    sources: list[ScoreSourceRow]


class ScoresResponse(BaseModel):
    """The scores cockpit: per-source + per-category + one composite INDEX, each with freshness and a
    plain-language review. `composite_index` is null when no category is live — never fabricated."""

    as_of: str
    composite_index: float | None = None
    composite_status: str
    composite_review: str
    categories: list[ScoreCategory]


# ---- Settings → Keys: a read-only inventory of which provider keys are configured. ----


class SettingsKeyRow(BaseModel):
    """One configurable secret/key, surfaced to the operator so they can see what's plugged vs missing.

    SECURITY: `configured` is a boolean only — the VALUE is NEVER read, returned, or logged. `requirement`
    is one of "required" (the app needs it to do its core job), "optional" (unlocks a paid/extra path), or
    "live-only" (only needed to move real money). `cost` is "free" or "paid". `where` tells the operator
    which env var to set on the engine."""

    key: str
    env_var: str
    configured: bool
    unlocks: str
    requirement: Literal["required", "optional", "live-only"]
    cost: Literal["free", "paid"]
    where: str


class SettingsKeysResponse(BaseModel):
    """Read-only key inventory for the Settings → Keys page. Values are never exposed — only whether each
    key is configured on the engine and what it unlocks. Safe to render in the browser."""

    rows: list[SettingsKeyRow]


# ---- News/intel panel: recent scored news events (typed, dated, point-in-time). ----


class NewsEventRow(BaseModel):
    """One recent scored news event from the `news_event_score` alt-data series.

    `ts` and `available_at` are ISO-8601 UTC strings (point-in-time, no look-ahead).
    `value` is the signed magnitude in [-1, 1] (sign × magnitude; the gate-readable number).
    `event_type` is the human-readable label ("bullish" / "bearish" / "neutral") derived from sign.
    `symbol` is the ticker this event was scored for (e.g. "BTCUSDT")."""

    ts: str | None = None
    available_at: str | None = None
    value: float
    event_type: Literal["bullish", "bearish", "neutral"]
    symbol: str


class NewsIntelResponse(BaseModel):
    """The news/intel panel: recent scored events, newest first.
    Honest empty state when no news has been ingested yet."""

    symbol: str
    events: list[NewsEventRow]

