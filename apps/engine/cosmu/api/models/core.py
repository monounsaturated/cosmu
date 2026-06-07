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
    # The REAL forward-test return: net-of-fee % from the LIVE marked trajectory (`tracks.return_pct`), marked
    # to market since the track's first `track_opened` for every asset class. This is the only number that
    # proves the edge forward — NOT the backtest. `null` when no track exists yet; a just-funded/un-marked
    # track reads 0.00 (day-0 truth), NEVER the rosy backtest (track_return_pct / net_pct = BACKTEST OOS).
    forward_return_pct: float | None = None
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
