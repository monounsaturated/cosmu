// Generated from apps/engine FastAPI OpenAPI. Do not edit by hand.

export interface ActivateRequest {
  confirm: boolean;
  global_cap: number;
  max_daily_loss: number;
  per_strategy_cap: number;
}

export interface ActivateResponse {
  armed: boolean;
  caps: LiveCaps;
  eligible: EligibleStrategy[];
  reason?: string | null;
}

export interface AssetClassState {
  active: boolean;
  enabled: boolean;
  has_data: boolean;
  kind: "crypto" | "equity" | "prediction";
  label: string;
}

export interface AuthorRequest {
  brief: string;
  features?: string[] | null;
  venues?: string[] | null;
}

export interface AuthorResponse {
  base_template: string;
  data_sources: string[];
  features: string[];
  guardrails: string[];
  issues: string[];
  name: string;
  notes: string[];
  rationale: string;
  requires_approval: boolean;
  spec: Record<string, unknown>;
  valid: boolean;
  venues: string[];
}

export interface AuthorRunRequest {
  brief: string;
  cohort_size?: number | null;
  features?: string[] | null;
  venues?: string[] | null;
}

export interface AutonomyPauseResponse {
  paused: boolean;
}

export interface AutonomyStatusResponse {
  cycles_run: number;
  last_action: string;
  last_summary: TickSummary;
  last_tick_at: string | null;
  live_enabled: boolean;
  next_action: string;
  paused: boolean;
  running: boolean;
}

export interface AutonomyTickAcceptedResponse {
  job_id: string;
  status: string;
}

export interface AutonomyTickJobResponse {
  error?: string | null;
  job_id: string;
  result?: AutonomyTickResponse | null;
  status: string;
}

export interface AutonomyTickResponse {
  authored: number;
  funded: number;
  gated_passed: number;
  recommendations: number;
}

export interface Backtest {
  deflated_sharpe: number;
  id: string;
  kind: string;
  max_dd: number;
  num_trades: number;
  oos_return: number;
  passed_gates: boolean;
  pbo: number;
  win_rate: number;
}

export interface BrainGated {
  generated: number;
  kill_rate: number;
  killed: number;
  passed: number;
}

export interface BrainGraveyard {
  name: string;
  reasons: string[];
}

export interface BrainRanking {
  name: string;
  score: number;
  trained: boolean;
  version_id: string;
}

export interface BrainRegime {
  label: string;
  trend: string;
  vol_bucket: string;
}

export interface BrainResponse {
  gated: BrainGated;
  graveyard: BrainGraveyard[];
  llm: "on" | "off";
  regime: BrainRegime;
  sources: BrainSource[];
  survival_ranking: BrainRanking[];
  survivors: BrainSurvivor[];
  tools: string[];
}

export interface BrainSource {
  kind: string;
  low_confidence: boolean;
  name: string;
}

export interface BrainSurvivor {
  name: string;
  net_pct: number;
  survival_score: number;
  version_id: string;
}

export interface ClassToggleRequest {
  active: boolean;
  kind: string;
}

export interface CohortRunRequest {
  cohort_size?: number | null;
  explore_pct?: number | null;
  pine_scripts?: string[] | null;
  seed?: number | null;
}

export interface CohortSummaryResponse {
  cohort_id: string;
  generated: number;
  graveyard: EvaluatedStrategy[];
  invalid: number;
  kill_rate: number;
  killed: number;
  lanes: Record<string, unknown>;
  passed: number;
  pine_imported: number;
  pine_notes: string[];
  seed: number;
  survivors: EvaluatedStrategy[];
}

export interface CommandRequest {
  text: string;
}

export interface CommandResponse {
  applied: boolean;
  parsed_policy: Record<string, unknown>;
  reply_md: string;
}

export interface CostByCategory {
  amount: number;
  category: string;
}

export interface CostPerStrategy {
  name: string;
  net: number;
  opex: number;
  version_id: string;
}

export interface CostSlice {
  amount: number;
  category: string;
}

export interface CostsResponse {
  by_category: CostByCategory[];
  infra_lines: InfraLine[];
  llm_calls: LlmCallSummary;
  opex_vs_alpha: number;
  per_strategy: CostPerStrategy[];
  total_usd: number;
  vendor_actuals: VendorActual[];
}

export interface CrossAssetVerdict {
  attempts: number;
  bar: Record<string, unknown>;
  buy_and_hold_return: number;
  cscv_pbo: number;
  data_source: "live" | "synthetic";
  decision: "PASS" | "STOP-narrow";
  drop_one_class: DropOneClass[];
  drop_one_source: DropOneSource[];
  max_drawdown: number;
  num_trades: number;
  passed: boolean;
  price_only_return: number;
  reasons: string[];
  regimes_positive: number;
  single_alt_dsr: number;
  single_alt_return: number;
  xasset_dsr: number;
  xasset_return: number;
}

export interface DataSource {
  last_at: string | null;
  points: number;
  source: string;
}

export interface DefundRequest {
  scope: "all" | "strategy";
  version_id?: string | null;
}

export interface DefundResponse {
  defunded: string[];
  ok: boolean;
}

export interface DriftResponse {
  tracks: DriftTrack[];
}

export interface DriftTrack {
  cusum: number;
  defund: boolean;
  half_life: number | null;
  n: number;
  periods_to_zero: number | null;
  realized_edge: number;
  reason: string;
  reference: string;
  reference_edge: number;
  version_id: string;
  z: number;
}

export interface DropOneClass {
  asset_class: string;
  delta: number;
  sharpe_without: number;
}

export interface DropOneSource {
  delta: number;
  sharpe_without: number;
  source: string;
}

export interface EligibleStrategy {
  name: string;
  version_id: string;
}

export interface EvaluatedStrategy {
  deflated_sharpe: number;
  lane: string;
  name: string;
  oos_return_pct: number;
  origin: string;
  passed: boolean;
  reasons: string[];
  version_id: string;
}

export interface Event {
  actor: string;
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  ref_id: string | null;
  ref_type: string | null;
  ts: string;
}

export interface EventsResponse {
  events: Event[];
}

export interface Execution {
  fee: number;
  id: string;
  price: number;
  qty: number;
  side: string;
  ts: string;
  venue: string | null;
}

export interface FinderResponse {
  gate_passed: number;
  grid_size: number;
  leaderboard: FinderVariant[];
  promoted: number;
  screened: number;
  strategy_name: string;
  survivors: FinderVariant[];
}

export interface FinderRunRequest {
  max_variants?: number | null;
  seed_real?: boolean;
}

export interface FinderVariant {
  config_tag: string;
  deflated_sharpe: number;
  gate_passed: boolean;
  holdout_passed: boolean;
  net_profit: number;
  num_trades: number;
  profit_factor: number;
  promoted: boolean;
  version_id: string | null;
}

export interface FunnelStats {
  authored: number;
  funded: number;
  gate_passed: number;
  killed: number;
  live: number;
  screened: number;
}

export interface GateEfficiency {
  current: number;
  improving: boolean;
  trend: number[];
}

export interface GateStatusResponse {
  preregistered_bar: Record<string, unknown>;
  verdict: GateVerdictResponse | null;
}

export interface GateVerdictResponse {
  attempts: number;
  bar: Record<string, unknown>;
  best_return: number;
  best_signal: string;
  buy_and_hold_return: number;
  cscv_pbo: number;
  data_source: string;
  decision: string;
  deflated_sharpe_prob: number;
  max_drawdown: number;
  num_trades: number;
  passed: boolean;
  reasons: string[];
  regimes_positive: number;
  ts: string;
}

export interface GraveyardRow {
  deflated_sharpe: number;
  kill_reason: string;
  name: string;
  origin: string;
  version_id: string;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface InboxIdeaRequest {
  name?: string | null;
  text: string;
}

export interface InboxIdeaResponse {
  filename: string;
  name: string;
  note: string;
  ok: boolean;
  queued: number;
}

export interface InboxQueueItem {
  filename: string;
  name: string;
  status: "queued" | "imported";
  ts: string;
}

export interface InboxQueueResponse {
  inbox_dir: string;
  items: InboxQueueItem[];
}

export interface InfraLine {
  amount: number;
  amount_max: number;
  amount_min: number;
  category: string;
  note: string;
  vendor: string;
}

export interface IntelligenceResponse {
  data_freshness: DataSource[];
  funnel: FunnelStats;
  gate_efficiency: GateEfficiency;
  lineage: LineageStats;
  memory: MemoryDepth;
  regime_coverage: RegimeCoverage;
  ticks: TickStats;
}

export interface JurisdictionOption {
  code: string;
  label: string;
  legal_venue_ids: string[];
}

export interface JurisdictionsResponse {
  current: string;
  options: JurisdictionOption[];
}

export interface LaunchActivateRequest {
  budget?: number;
  confirm: boolean;
  global_cap?: number;
  max_daily_loss?: number;
  override_forward_test?: boolean;
  per_strategy_cap?: number;
  symbol: string;
  venue_id: string;
  version_id: string;
}

export interface LaunchActivateResponse {
  armed: boolean;
  budget: number;
  caps: LiveCaps;
  eligible: EligibleStrategy[];
  forward_test_days?: number | null;
  overridden?: boolean;
  readiness?: "proven" | "not yet proven";
  reason?: string | null;
  symbol: string;
  venue_id: string;
  version_id: string;
}

export interface LeaderboardResponse {
  rows: LeaderboardRow[];
}

export interface LeaderboardRow {
  asset_class: string;
  deflated_sharpe: number;
  edge_type: string;
  features: string[];
  forward_age_days: number;
  lineage: string;
  live_ready: boolean;
  name: string;
  net_pct: number;
  origin: string;
  pbo: number;
  signal_family: string;
  signal_family_label: string;
  status: string;
  timeframe: string;
  track_return_pct: number;
  venue: string;
  version_id: string;
}

export interface LineageEntry {
  operator?: string | null;
  origin?: string | null;
  passed: number;
  rate: number;
  total: number;
}

export interface LineageStats {
  by_operator: LineageEntry[];
  by_origin: LineageEntry[];
}

export interface LiveCaps {
  global_cap: number;
  max_daily_loss: number;
  per_strategy_cap: number;
}

export interface LivePosition {
  avg_price: number;
  instrument_id: string;
  qty: number;
  symbol: string;
  unrealized_pnl: number;
  venue: string;
}

export interface LivePositionsResponse {
  armed: boolean;
  caps: LiveCaps;
  daily_loss: number;
  mode: "testnet" | "live" | "sim";
  positions: LivePosition[];
}

export interface LiveVenue {
  connected: boolean;
  deployed_usd: number;
  enabled: boolean;
  id: string;
  kind: "crypto" | "equity" | "prediction";
  live_legal: boolean;
  name: string;
}

export interface LiveVenuesResponse {
  global_cap: number;
  jurisdiction: string;
  total_deployed_usd: number;
  venues: LiveVenue[];
}

export interface LlmCallSummary {
  by_task: Record<string, unknown>;
  call_count: number;
  total_cost: number;
}

export interface MemoryDepth {
  dead_ends: number;
  skills: number;
  total: number;
  winners: number;
}

export interface MemoryInsight {
  kind: "dead_end" | "winner_pattern";
  ref: string;
  text: string;
}

export interface MemoryInsightsResponse {
  insights: MemoryInsight[];
}

export interface MindAuditContribution {
  contribution: number;
  conviction: number;
  lean: string;
  perspective: string;
  source: string;
  weight: number;
}

export interface MindConsensusAudit {
  consensus: string;
  contributions: MindAuditContribution[];
  method: string;
  tally: Record<string, unknown>;
  total: number;
}

export interface MindLearnings {
  dead_ends: number;
  gate_improving: boolean;
  gate_rate: number;
  gate_trend: number[];
  insights: MemoryInsight[];
  ml_auroc?: number | null;
  ml_backend: string;
  ml_labels: number;
  ml_trained: boolean;
  regime_covered: number;
  regime_grid: RegimeCell[];
  regime_total: number;
  skills: number;
  winners: number;
}

export interface MindLens {
  ingested: number;
  items: MindSourceItem[];
  perspective: string;
  total: number;
}

export interface MindResponse {
  agreement: number;
  as_of?: string | null;
  bear_case: string[];
  bull_case: string[];
  consensus: "bullish" | "bearish" | "neutral";
  consensus_audit?: MindConsensusAudit | null;
  contested: boolean;
  conviction: number;
  knows: MindLens[];
  learnings: MindLearnings;
  narrative: string;
  railguard: string;
  stances: MindStance[];
}

export interface MindSourceItem {
  ingested: boolean;
  last_at?: string | null;
  low_confidence?: boolean;
  name: string;
  prior: string;
  source: string;
  tier: string;
  value?: number | null;
}

export interface MindStance {
  as_of?: string | null;
  conviction: number;
  evidence: string[];
  headline: string;
  kind: "market" | "process";
  lean: "bullish" | "bearish" | "neutral" | "abstain";
  low_confidence?: boolean;
  perspective: string;
  rationale: string;
  rubric?: string | null;
  score?: number;
  source?: "heuristic" | "llm" | "abstain";
  weight: number;
}

export interface MlFeatureWeight {
  feature: string;
  weight: number;
}

export interface MlRankedItem {
  deflated_sharpe: number;
  gate_passed: boolean;
  name: string;
  score: number;
  version_id: string;
}

export interface MlRequest {
  limit?: number | null;
  request: string;
}

export interface MlResponse {
  backend: string;
  feature_importance: MlFeatureWeight[];
  llm: string;
  n_labels: number;
  notes: string[];
  ranking: MlRankedItem[];
  request: string;
  task: "survival_ranking" | "feature_importance";
  trained: boolean;
}

export interface NewsEventRow {
  available_at?: string | null;
  event_type: "bullish" | "bearish" | "neutral";
  symbol: string;
  ts?: string | null;
  value: number;
}

export interface NewsIntelResponse {
  events: NewsEventRow[];
  symbol: string;
}

export interface OverviewResponse {
  costs: CostSlice[];
  equity_curve: Point[];
  live_enabled: boolean;
  opex_vs_alpha: number;
  pnl_net: number;
}

export interface PineSample {
  name: string;
  source: string;
}

export interface PineSamplesResponse {
  samples: PineSample[];
}

export interface PineTranslateRequest {
  source: string;
}

export interface PineTranslateResponse {
  conditions: string[];
  indicators: string[];
  lifted_params: Record<string, unknown>;
  name: string;
  notes: string[];
  param_count: number;
  spec: Record<string, unknown>;
}

export interface Point {
  ts: string;
  value: number;
}

export interface PopulationResponse {
  by_lane: Record<string, unknown>;
  by_origin: Record<string, unknown>;
  forward_test: number;
  graveyard: GraveyardRow[];
  kill_rate: number;
  killed: number;
  live: number;
  total: number;
}

export interface Recommendation {
  body: string;
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  state: "open" | "approved" | "dismissed";
  ts: string;
}

export interface RecommendationActionResponse {
  applied?: boolean;
  ok: boolean;
  reason?: string | null;
}

export interface RecommendationsResponse {
  items: Recommendation[];
}

export interface RegimeCell {
  regime: string;
  strategies: number;
  trend: string;
  vol: string;
}

export interface RegimeCoverage {
  by_label: Record<string, unknown>;
  covered: number;
  grid: RegimeCell[];
  total: number;
}

export interface ScoreCategory {
  connected: boolean;
  freshness_label: string;
  index_score?: number | null;
  key: string;
  label: string;
  live_sources: number;
  review: string;
  sources: ScoreSourceRow[];
  status: string;
  total_sources: number;
}

export interface ScoreSourceRow {
  category: string;
  connected: boolean;
  disabled: boolean;
  features: string[];
  freshness_label: string;
  hours_since?: number | null;
  key_name?: string | null;
  key_present: boolean;
  key_required: boolean;
  last_at?: string | null;
  review: string;
  source: string;
  status: "fresh" | "recent" | "aging" | "stale" | "no data";
  tier: string;
  trust_score: number;
}

export interface ScoresResponse {
  as_of: string;
  categories: ScoreCategory[];
  composite_index?: number | null;
  composite_review: string;
  composite_status: string;
}

export interface SetJurisdictionRequest {
  code: string;
}

export interface SettingsKeyRow {
  configured: boolean;
  cost: "free" | "paid";
  env_var: string;
  key: string;
  requirement: "required" | "optional" | "live-only";
  unlocks: string;
  where: string;
}

export interface SettingsKeysResponse {
  rows: SettingsKeyRow[];
}

export interface Skill {
  created_at: string;
  grade: number;
  lineage: string;
  name: string;
  recipe_summary: string;
  success_count: number;
}

export interface SkillsResponse {
  skills: Skill[];
}

export interface SourceTrustResponse {
  as_of: string;
  rows: SourceTrustRow[];
}

export interface SourceTrustRow {
  features: string[];
  freshness_label: string;
  gate_pass_count: number;
  hours_since?: number | null;
  last_at?: string | null;
  source: string;
  status: "fresh" | "recent" | "aging" | "stale" | "no data";
  summary: string;
  tier: string;
  trust_score: number;
}

export interface StrategyDetailResponse {
  backtests: Backtest[];
  generated_code: string;
  holdout: Record<string, unknown>;
  name: string;
  notes_md: string;
  params: Record<string, unknown>;
  spec: Record<string, unknown>;
  trades: Execution[];
  version_id: string;
}

export interface TickDetail {
  authored: number;
  funded: number;
  passed: number;
}

export interface TickStats {
  avg_survivors_per_tick: number;
  last_at: string | null;
  recent: TickDetail[];
  total: number;
  total_authored: number;
  total_survivors: number;
}

export interface TickSummary {
  authored: number;
  funded: number;
  gated_passed: number;
  recommendations: number;
}

export interface ToggleRequest {
  confirm: boolean;
  enabled: boolean;
}

export interface ToggleResponse {
  caps: Record<string, unknown>;
  enabled: boolean;
  promoted: string[];
  reason?: string | null;
  requires_confirm?: boolean;
}

export interface UniverseResponse {
  asset_classes: AssetClassState[];
  venues: VenueState[];
}

export interface ValidationError {
  loc: string | number[];
  msg: string;
  type: string;
}

export interface VendorActual {
  amount: number;
  budget: number;
  category: string;
  period: string;
  vendor: string;
}

export interface VenueCatalogResponse {
  instruments: VenueInstrumentInfo[];
  venues: VenueFeeInfo[];
}

export interface VenueFeeInfo {
  configured: boolean;
  fee_tiers: VenueFeeTierInfo[];
  id: string;
  kind: "crypto" | "equity" | "prediction";
  live_enabled: boolean;
  maker_fee_bps: number;
  min_notional: number;
  name: string;
  taker_fee_bps: number;
}

export interface VenueFeeTierInfo {
  maker_fee_bps: number;
  min_volume_30d_usd: number;
  taker_fee_bps: number;
}

export interface VenueInstrumentInfo {
  asset_class: "crypto" | "equity" | "prediction";
  id: string;
  min_notional: number;
  symbol: string;
  venue_id: string;
}

export interface VenueState {
  effective: boolean;
  enabled: boolean;
  has_data: boolean;
  id: string;
  kind: "crypto" | "equity" | "prediction";
  name: string;
}

export interface VenueToggleRequest {
  enabled: boolean;
  venue_id: string;
}

export type ApiRoutes = {
  overview: OverviewResponse;
  leaderboard: LeaderboardResponse;
  recommendations: RecommendationsResponse;
  events: EventsResponse;
  skills: SkillsResponse;
  'memory/insights': MemoryInsightsResponse;
  costs: CostsResponse;
};
