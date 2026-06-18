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
    paper tracks. This is a pure read-out — there is NO pooled wallet and no cross-track allocation."""

    equity_curve: list[Point]
    pnl_net: float
    costs: list[CostSlice]
    live_enabled: bool
    opex_vs_alpha: float


class PortfolioSummaryResponse(BaseModel):
    """The live-vs-sim money split for the v18 dashboards/ribbon — the one read-out that must NEVER label SIM
    capital as live. The ONLY honest position-row discriminator is `venue != 'sim'` (positions carry no mode
    column), so the live figures are reconstructed from those rows.

    HONESTY CONTRACT: when no position is routed live (`has_live` False) every `live_*` money figure is `None`
    so the UI renders an explicit "—", never 0 and never the SIM number. `live_free` is BUDGET HEADROOM
    (`live_global_cap − live_invested`), NOT a fetched exchange cash balance (the engine never reads broker
    cash). `live_equity` is `None` until a real live portfolio snapshot is persisted (none is today)."""

    has_live: bool
    live_armed: bool
    live_mode: Literal["testnet", "live", "sim"]
    sim_equity: float
    sim_pnl_net: float
    live_equity: float | None = None
    live_invested: float | None = None
    live_free: float | None = None  # budget headroom (global_cap − invested), NOT exchange cash
    live_pnl_net: float | None = None
    live_unrealized: float | None = None
    live_realized: float | None = None
    live_global_cap: float
    positions_count_live: int


class LeaderboardRow(BaseModel):
    version_id: str
    name: str
    # The strategy MODEL discriminator (strategy_versions.kind) — "quant" = a typed StrategySpec routed through
    # deterministic Gate A (the only model today), "llm" = an agentic/NL AgentSpec. NOTE: this is the model kind,
    # NOT the asset-class `kind: Literal["crypto","equity","prediction"]` other models in this file carry.
    kind: Literal["quant", "llm"] = "quant"
    track_return_pct: float
    deflated_sharpe: float
    net_pct: float
    pbo: float
    status: str
    lineage: str
    # The REAL paper return: net-of-fee % from the LIVE marked trajectory (`tracks.return_pct`), marked
    # to market since the track's first `track_opened` for every asset class. This is the only number that
    # proves the edge forward — NOT the backtest. `null` when no track exists yet; a just-funded/un-marked
    # track reads 0.00 (day-0 truth), NEVER the rosy backtest (track_return_pct / net_pct = BACKTEST OOS).
    paper_return_pct: float | None = None
    # ADVISORY paper maturity signal (master/paper_maturity.py) — SURFACED, NOT ENFORCED. `paper_age_days`
    # is calendar time the track's paper clock has run since its first mark; `live_ready` recommends a track
    # that has both matured (>= PAPER_MIN_DAYS) and is net-of-fee positive. The operator launches via the
    # modal at their discretion; the 5 interlocks remain the only hard gate. Never consulted by the gate/money path.
    paper_age_days: float
    live_ready: bool
    # ADVISORY SIM-vs-backtest divergence read-out (master/divergence.py) — SURFACED, NEVER ENFORCED. An early
    # warning that this track's REAL marked forward return has stopped tracking the backtest it was funded on
    # (alpha-decay / regime-shift). `divergence_status` is "tracking" / "diverging" / "insufficient" (the honest
    # empty state when the marked window is too short); `divergence_gap_pct` is the signed percentage-point gap
    # between the marked forward return and the backtest pro-rated to the SAME elapsed window (negative = the live
    # track is under-performing the backtest). MONITORING ONLY — never on the Gate/scorer/FDR/money path.
    divergence_status: Literal["insufficient", "tracking", "diverging"] = "insufficient"
    divergence_gap_pct: float | None = None
    # v18 display columns — REAL marked money, net of fees, never fabricated. `value_usd` is the track's
    # marked-to-market equity (latest scope='track' snapshot); `pnl_usd` = value_usd - starting_capital;
    # `pnl_pct` ALIASES the already-computed `paper_return_pct` (the forward number) so the $ and % can never
    # disagree and the rosy backtest is never surfaced. All `null` until the track is marked (day-0 truth) —
    # the screener renders an honest "—", NOT 0 or a -100% loss. `oos_window_days` is the backtest OOS window
    # length (from the YYYY-MM bounds), so the OOS % can be shown WITH its window ("+8.2% over ~2.4yr"); null
    # when the bounds are missing/malformed.
    # The honest "has this track traded on paper" flag = a real paper fill exists in the executions ledger
    # (is_paper=1), the SAME signal the detail sheet's blotter reads. The web keys the "Paper" badge + the
    # Paper cohort off THIS (not raw status), so a funded-but-never-filled documented arm can never show
    # "Paper" while its own sheet says "no fills yet". When false, the marked money fields below are None.
    has_paper_fills: bool = False
    # Trades made at the strategy's LATEST stage — the count of paper fills (executions, is_paper=1) when the
    # track has traded, else the strongest backtest's round-trips (`backtests.num_trades`). So the number always
    # matches the stage the rest of the row reports (paper money vs backtest OOS). `null` when neither exists.
    trades: int | None = None
    value_usd: float | None = None
    pnl_usd: float | None = None
    pnl_pct: float | None = None
    oos_window_days: float | None = None
    # Max drawdown from the STRONGEST backtest (peak-to-trough fraction, 0..1). Surfaced so the Strategies
    # table can show the real worst-case drop alongside the OOS return and DSR — honest "—" when no backtest.
    max_dd: float | None = None
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
    # `deflated_sharpe` is the deflated-Sharpe RATIO (a risk-adjusted RANKING number, can exceed 1.0) — NOT the
    # value the Gate's 0.95 bar checks. The Gate gates on `deflated_sharpe_prob` below: the PROBABILITY in [0,1]
    # that the edge is real after the multiple-testing penalty. Surfacing both, distinctly labelled, is what keeps
    # the sheet from reading "deflated-Sharpe 0.98 — below the 0.95 bar" (a ratio compared to a probability bar).
    deflated_sharpe: float
    # The GATED metric: deflated-Sharpe PROBABILITY in [0,1], recomputed (master/scorer.deflated_sharpe_prob) from
    # this row's persisted survival inputs (sharpe_per_obs/skew/kurtosis/n_obs/trials_counted). None when those
    # columns are absent (pre-migration / arm rows) — the UI then falls back to passed_gates (≥/< 0.95). Verified
    # prod-wide: where computable, prob ≥ 0.95 ⟺ passed_gates, so the displayed number never contradicts the verdict.
    deflated_sharpe_prob: float | None = None
    max_dd: float
    win_rate: float
    num_trades: int
    pbo: float
    passed_gates: bool
    # Length of the OOS window in days (from the YYYY-MM bounds) so the sheet's "Duration" row shows the OOS %
    # WITH its window ("+8.2% over ~2.4yr") instead of the literal "OOS". None when the bounds are missing.
    oos_window_days: float | None = None


class StrategyDetailResponse(BaseModel):
    version_id: str
    name: str
    # The strategy MODEL discriminator (strategy_versions.kind) — "quant" = a typed StrategySpec routed through
    # deterministic Gate A (the only model today), "llm" = an agentic/NL AgentSpec. NOTE: this is the model kind,
    # NOT an asset-class kind.
    kind: Literal["quant", "llm"] = "quant"
    spec: dict[str, Any]
    generated_code: str
    params: dict[str, Any]
    trades: list[Execution]
    backtests: list[Backtest]
    notes_md: str
    holdout: dict[str, Any]
    # Plain-language summary (latest research_notes row kind='summary') — WRITTEN EXTERNALLY by the operator's
    # agent (Claude Code, flat sub), never generated by the deployed engine. ADVISORY, not the gate. Honest
    # nulls when no summary row exists. summary_stale=True when the stored facts_hash no longer matches the
    # current summary_facts() hash — the numbers changed since the summary was written.
    summary_md: str | None = None
    summary_stale: bool | None = None
    summary_updated_at: str | None = None
    # REAL marked forward money — the SAME honest source the leaderboard/costs routers already serve, NEVER the
    # execution cash flow and NEVER tracks.equity (the stale backtest SEED). `value_usd` = latest scope='track'
    # snapshot equity (marked positions_value + cash). `invested_usd` = deployed cost basis (Σ avg_price*qty over
    # the version's positions). `realized_pnl` = Σ positions.realized_pnl (0 until a CLOSE — an opening buy books
    # only its fee, so a buy-and-hold track is honestly 0, never -100%). `unrealized_pnl` = pnl_usd - realized_pnl.
    # `pnl_usd` = value_usd - starting_capital (identical to the leaderboard's pnl_usd, so the two surfaces agree).
    # ALL of these are None until the track has BOTH a real paper fill (`has_paper_fills`) AND a marked snapshot —
    # the sheet then renders "—" across the whole money band (never a split where one cell is real and another "—",
    # and never a fabricated loss from buy notionals).
    has_paper_fills: bool = False
    value_usd: float | None = None
    invested_usd: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    pnl_usd: float | None = None
    starting_capital: float | None = None
    # The honest forward EQUITY trajectory = the scope='track' portfolio_snapshot history (marked value over time),
    # oldest-first. The sheet's equity chart renders THIS — never the cumulative-cash-flow-of-buys curve (which
    # sloped to -100%). Empty until the track is marked → the chart shows its honest empty state.
    forward_equity: list[Point] = []


class SummaryFactsResponse(BaseModel):
    """The DETERMINISTIC facts a plain-language summary is written from (research/summary_facts.py) plus the
    sha256 staleness pin. The external writer GETs this, writes prose from these facts ONLY, and PUTs the
    summary back pinned to this exact facts_hash."""

    facts: dict[str, Any]
    facts_hash: str


class StrategySummaryPutRequest(BaseModel):
    """An externally-written summary being stored: the markdown body + the facts_hash it was written from
    (the staleness pin) + writer provenance (model, prompt_version). The engine stores/serves — never writes."""

    body_md: str
    facts_hash: str
    model: str
    prompt_version: str


class StrategySummaryPutResponse(BaseModel):
    ok: bool


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


class VenueRule(BaseModel):
    """A venue row in the Rules modal: its hard per-venue notional cap (None = uncapped) and the REAL capital
    deployed on it now (so the operator sees headroom = cap − deployed). `available_usd` is the deployed
    figure's complement under the cap (cap − deployed), or None when the venue is uncapped — it is budget
    headroom, NOT a fetched exchange balance."""

    venue: str
    name: str
    max_notional: float | None = None
    deployed_usd: float
    available_usd: float | None = None


class RulesResponse(BaseModel):
    """The live-trading Rules: the hard global $ blocker + daily-loss + per-venue caps. Enforced
    deterministically in the order gauntlet (per-venue caps only when live is armed; the SIM lane is never
    constrained). Read-only here; POST /live/rules sets them."""

    global_max_notional: float
    max_daily_loss: float
    per_strategy_cap: float
    venues: list[VenueRule]


class VenueRuleSet(BaseModel):
    venue: str
    max_notional: float | None = None  # None clears the per-venue cap


class RulesRequest(BaseModel):
    global_max_notional: float | None = None
    max_daily_loss: float | None = None
    venues: list[VenueRuleSet] = []


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
    slippage_bps: float        # per-venue market depth: the fixed half-spread the backtest charges here
    impact_bps: float          # per-venue market depth: the size-aware impact coefficient
    region: str | None         # operating region / hosting hint (honest metadata — NOT the legality gate)
    legal_entity: str | None   # the regulated entity we'd contract with (honest metadata — NOT the gate)
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
    `override_paper` (default OFF) is the explicit human escape hatch: arm a strategy that has NOT
    yet cleared the >= PAPER_MIN_DAYS net-positive paper precondition, recorded with a loud
    `live_override_launch` warning event. It never waives the regime gate or the 5 execution interlocks."""

    version_id: str
    venue_id: str
    symbol: str
    budget: float = 100.0
    per_strategy_cap: float = 100.0
    global_cap: float = 1000.0
    max_daily_loss: float = 50.0
    confirm: bool
    override_paper: bool = False


class LaunchActivateResponse(BaseModel):
    """Result of the launch-live flow for one strategy.
    `armed` = eligibility + the 5 interlocks cleared and the strategy is now live (status='live' written here).
    `paper_days` = paper maturity in days (None = no track yet).
    `readiness` = "proven" (>= PAPER_MIN_DAYS forward days net-positive) or "not yet proven". This is now
    a HARD precondition for arming, not merely advisory: a "not yet proven" strategy is refused (armed=False)
    unless the human sets `override_paper`.
    `overridden` = True when the human waived the paper precondition to arm an unproven strategy."""

    armed: bool
    version_id: str
    venue_id: str
    symbol: str
    budget: float
    caps: LiveCaps
    eligible: list[EligibleStrategy]
    paper_days: float | None = None   # how many real paper days this track has (None = no track)
    readiness: Literal["proven", "not yet proven"] = "not yet proven"
    overridden: bool = False                 # True when arming waived the paper precondition (logged)
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


# --- Correlation engine (read-only, propose-only) -------------------------------------------------------------
# These models carry the correlation_ledger (correlation_findings table) shape to the frontend. The correlation
# engine FINDS correlations (even non-causal), TRACKS them run-over-run, and DISPLAYS them; it NEVER gates or
# moves money — the deterministic Gate is the disposal layer ("scan proposes, Gate disposes"). Every field is
# PIT-honest, sourced from a persisted finding; the empty state is honest empty arrays, never fabricated.


class CorrelationFinding(BaseModel):
    """One persisted correlation_scan finding (one row of correlation_findings): the PIT IC of a feature against
    a forward return for one asset × horizon, with its sample size, p-value, and BH-FDR survival. `non_causal`
    is DERIVED from `deflated_note` (a registered non-causal / orthogonality control feature) so the UI never lets
    a known-false baseline masquerade as an edge — a strong IC there is a data-snooping red flag, not a hypothesis.
    Propose-only: a finding is a candidate correlation, never an edge."""

    run_id: str
    ts: str
    feature: str
    source: str
    asset: str
    horizon: int
    ic: float
    n: int
    p: float
    fdr_survived: bool
    non_causal: bool       # derived from deflated_note — a registered non-causal/orthogonality control
    deflated_note: str     # honest one-line causal-trust note (empty for a plain causal feature)
    data_source: str       # "live" vs a fixture tag, so a test never reads as live correlation memory


class CorrelationHeatmapCell(BaseModel):
    """One cell of the compact IC heatmap (feature × asset for a single horizon): the IC of `feature` against the
    forward return of `asset` at the heatmap's pinned horizon, plus its FDR survival + non-causal flag so the UI
    can shade survivors and grey-out known-false controls."""

    feature: str
    asset: str
    ic: float
    fdr_survived: bool
    non_causal: bool


class CorrelationHeatmap(BaseModel):
    """A compact IC heatmap for ONE horizon: the axes (sorted feature + asset names) and the populated cells.
    Sparse — only (feature, asset) pairs the latest run actually measured at this horizon appear in `cells`.
    `horizon` is None (and the axes/cells empty) in the honest empty state where no findings exist yet."""

    horizon: int | None
    features: list[str]
    assets: list[str]
    cells: list[CorrelationHeatmapCell]


class CorrelationStabilityPoint(BaseModel):
    """One run's IC for a feature×asset×horizon series — a point on the decay curve (oldest-first in the series)."""

    run_id: str
    ts: str
    ic: float
    fdr_survived: bool


class CorrelationStability(BaseModel):
    """Per-feature stability/decay: the IC history of ONE feature (pinned to its strongest-|IC| asset × horizon from
    the latest run) across runs, oldest-first — the tell a single scan print can't show. `latest_ic` is the most
    recent point; `delta_ic` is latest minus first (negative = the correlation is decaying run-over-run). A
    single-run series carries delta_ic = 0.0 (no decay measurable yet)."""

    feature: str
    asset: str
    horizon: int
    non_causal: bool
    latest_ic: float
    first_ic: float
    delta_ic: float        # latest_ic - first_ic; negative = decaying
    n_runs: int
    history: list[CorrelationStabilityPoint]


class CorrelationsResponse(BaseModel):
    """The correlation-engine read-out for the frontend, all from the correlation_ledger. `latest` is the most
    recent run's findings; `survivors` is the BH-FDR-surviving subset (candidate hypotheses); `heatmap` is a
    compact feature × asset IC grid for one horizon; `stability` tracks each feature's IC across runs (decay).
    `latest_run_id` ties the latest set together. HONEST EMPTY STATE: no findings yet → empty arrays + a null
    heatmap horizon, never fabricated. Read-only, propose-only — NEVER a Gate or money action."""

    latest_run_id: str | None
    latest: list[CorrelationFinding]
    survivors: list[CorrelationFinding]
    heatmap: CorrelationHeatmap
    stability: list[CorrelationStability]
