// Generated from apps/engine FastAPI OpenAPI. Do not edit by hand.

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

export interface CostSlice {
  amount: number;
  category: string;
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

export interface RecommendationsResponse {
  items: Recommendation[];
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

export interface ToggleRequest {
  confirm: boolean;
  enabled: boolean;
}

export interface ToggleResponse {
  caps: Record<string, unknown>;
  enabled: boolean;
  promoted: string[];
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
};
