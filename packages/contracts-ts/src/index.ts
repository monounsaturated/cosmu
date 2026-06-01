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

export interface Allocation {
  capital: number;
  name: string;
  strategy_id: string;
  venue: string;
  weight: number;
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
  opex_vs_alpha: number;
  per_strategy: CostPerStrategy[];
  total_usd: number;
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

export interface DefundRequest {
  scope: "all" | "strategy";
  version_id?: string | null;
}

export interface DefundResponse {
  defunded: string[];
  ok: boolean;
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

export interface LeaderboardResponse {
  rows: LeaderboardRow[];
}

export interface LeaderboardRow {
  deflated_sharpe: number;
  lineage: string;
  name: string;
  net_pct: number;
  pbo: number;
  sleeve_return_pct: number;
  status: string;
  version_id: string;
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
  mode: "testnet" | "live" | "paper";
  positions: LivePosition[];
}

export interface MemoryInsight {
  kind: "dead_end" | "winner_pattern";
  ref: string;
  text: string;
}

export interface MemoryInsightsResponse {
  insights: MemoryInsight[];
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
  graveyard: GraveyardRow[];
  kill_rate: number;
  killed: number;
  paper: number;
  total: number;
}

export interface PortfolioResponse {
  allocation: Allocation[];
  costs: CostSlice[];
  equity_curve: Point[];
  live_enabled: boolean;
  opex_vs_alpha: number;
  pnl_net: number;
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
  portfolio: PortfolioResponse;
  leaderboard: LeaderboardResponse;
  recommendations: RecommendationsResponse;
  events: EventsResponse;
  skills: SkillsResponse;
  'memory/insights': MemoryInsightsResponse;
  costs: CostsResponse;
};
