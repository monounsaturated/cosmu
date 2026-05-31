// Generated from apps/engine FastAPI OpenAPI. Do not edit by hand.

export interface Allocation {
  capital: number;
  name: string;
  strategy_id: string;
  venue: string;
  weight: number;
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

export interface Point {
  ts: string;
  value: number;
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

export interface ValidationError {
  loc: string | number[];
  msg: string;
  type: string;
}

export type ApiRoutes = {
  portfolio: PortfolioResponse;
  leaderboard: LeaderboardResponse;
  recommendations: RecommendationsResponse;
  events: EventsResponse;
};
