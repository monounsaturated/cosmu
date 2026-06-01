// module: product data adapter. Purpose: feed the four Cosmu surfaces from the generated engine contract with local fallback for build-safe QA. Invariants: no secrets in the browser and no hand-written server contract drift.

import type {
  Backtest,
  CohortSummaryResponse,
  Event,
  LeaderboardResponse,
  PopulationResponse,
  PortfolioResponse,
  Recommendation,
  StrategyDetailResponse
} from "@cosmu/contracts-ts";
import type { PositionsResponse } from "@/components/live/contracts";

const baseUrl = process.env.ENGINE_API_URL;

// Honest engine reachability. The server-rendered surfaces fetch the REAL engine; the only
// fabricated numbers allowed are the clearly-labelled DEMO returned when the engine is
// unreachable (no ENGINE_API_URL, or the fetch failed). `meta.demo` lets the UI say so out loud.
async function getJson<T>(path: string, fallback: T): Promise<{ data: T; demo: boolean }> {
  if (!baseUrl) return { data: fallback, demo: true };
  try {
    const response = await fetch(`${baseUrl}${path}`, { next: { revalidate: 5 } });
    if (!response.ok) return { data: fallback, demo: true };
    return { data: (await response.json()) as T, demo: false };
  } catch {
    return { data: fallback, demo: true };
  }
}

// HONEST EMPTY STATE: when there is no real engine paper portfolio yet, we show nothing
// fabricated — zeroed money, empty allocation, an empty equity curve. The UI renders a
// "no live data yet" empty state from this rather than inventing a track record.
export const emptyPortfolio: PortfolioResponse = {
  equity_curve: [],
  pnl_net: 0,
  allocation: [],
  costs: [],
  live_enabled: false,
  opex_vs_alpha: 0
};

// DEMO ONLY — clearly labelled, used solely when the engine is unreachable so the app still
// renders offline. Never presented as a real track record (the UI tags it "demo data").
const demoEquityCurve = Array.from({ length: 48 }, (_, index) => {
  const value = 100000 + index * 178 + Math.sin(index / 3) * 900 - Math.max(0, index - 35) * 60;
  return { ts: `T-${47 - index}`, value: Math.round(value) };
});

export const demoPortfolio: PortfolioResponse = {
  equity_curve: demoEquityCurve,
  pnl_net: demoEquityCurve[demoEquityCurve.length - 1].value - 100000,
  allocation: [
    { strategy_id: "sv-btc", name: "Funding-aware BTC swing", weight: 0.42, capital: 42000, venue: "Binance" },
    { strategy_id: "sv-equity", name: "Equity macro drift", weight: 0.31, capital: 31000, venue: "IBKR" },
    { strategy_id: "sv-pm", name: "Prediction odds transfer", weight: 0.27, capital: 27000, venue: "Polymarket" }
  ],
  costs: [
    { category: "llm", amount: 18.4 },
    { category: "data", amount: 7.2 },
    { category: "sandbox", amount: 4.8 },
    { category: "infra", amount: 3.1 }
  ],
  live_enabled: false,
  opex_vs_alpha: 0.18
};

export const fallbackLeaderboard: LeaderboardResponse = {
  rows: [
    { version_id: "sv-btc", name: "Funding-aware BTC swing", sleeve_return_pct: 6.8, deflated_sharpe: 1.21, net_pct: 6.42, pbo: 0.22, status: "paper", lineage: "seed -> wfo -> holdout" },
    { version_id: "sv-equity", name: "Equity macro drift", sleeve_return_pct: 4.1, deflated_sharpe: 0.94, net_pct: 3.88, pbo: 0.31, status: "paper", lineage: "chat -> mutate -> wfo" },
    { version_id: "sv-pm", name: "Prediction odds transfer", sleeve_return_pct: 3.4, deflated_sharpe: 0.77, net_pct: 3.18, pbo: 0.38, status: "screening", lineage: "mined -> screen" },
    { version_id: "sv-dead", name: "Mean reversion after liquidations", sleeve_return_pct: -2.5, deflated_sharpe: -0.22, net_pct: -2.9, pbo: 0.74, status: "killed", lineage: "wildcard -> killed: pbo" }
  ]
};

const fallbackBacktests: Backtest[] = [
  { id: "bt-wfo", kind: "wfo", oos_return: 0.068, deflated_sharpe: 1.21, max_dd: 0.08, win_rate: 0.57, num_trades: 34, pbo: 0.22, passed_gates: true },
  { id: "bt-holdout", kind: "holdout", oos_return: 0.019, deflated_sharpe: 0.35, max_dd: 0.04, win_rate: 0.55, num_trades: 11, pbo: 0.2, passed_gates: true }
];

export const fallbackStrategy: StrategyDetailResponse = {
  version_id: "sv-btc",
  name: "Funding-aware BTC swing",
  spec: {
    hypothesis: "Buy medium-term BTC strength only when volatility and funding imply a durable risk-on impulse.",
    universe: ["BTCUSDT", "ETHUSDT"],
    entry: ["ret_Nd > entry_ret", "vol_realized > vol_floor"],
    exit: ["stop_loss", "take_profit", "time_stop"]
  },
  generated_code: "COSMU_STRATEGY_V1 = { spec, params }",
  params: { entry_ret: 0.03, vol_floor: 0.02, stop: 0.06, take: 0.12 },
  trades: [
    { id: "ex-1", side: "buy", qty: 0.015, price: 65040, fee: 0.98, venue: "binance", ts: "paper T-11" },
    { id: "ex-2", side: "sell", qty: 0.015, price: 67680, fee: 1.02, venue: "binance", ts: "paper T-4" }
  ],
  backtests: fallbackBacktests,
  notes_md: "Passed deterministic WFO and untouched holdout. Keep in realistic paper until it survives 4+ weeks with positive net edge at fillable size.",
  holdout: { passed: true, deflated_sharpe: 0.35, seen_once: true }
};

export const fallbackRecommendations: Recommendation[] = [
  {
    id: "rec-1",
    ts: "now",
    kind: "paper_promotion_watch",
    body: "One strategy cleared WFO + holdout. Keep it in paper for 4 weeks before live eligibility.",
    state: "open",
    payload: { next_gate: "realistic_paper_survival" }
  },
  {
    id: "rec-2",
    ts: "now-1h",
    kind: "cost_throttle",
    body: "LLM and sandbox spend is 18% of trailing paper edge. Routing stays cheap-tier first.",
    state: "open",
    payload: { opex_vs_alpha: 0.18 }
  }
];

export const fallbackEvents: Event[] = [
  { id: 101, ts: "now", actor: "master", kind: "run_completed", ref_type: "run", ref_id: "run-1", payload: { fills: 8, passed: true } },
  { id: 100, ts: "now-4m", actor: "agent", kind: "spec_authored", ref_type: "strategy_version", ref_id: "sv-btc", payload: { validated: true } },
  { id: 99, ts: "now-8m", actor: "master", kind: "gate_passed", ref_type: "backtest", ref_id: "bt-wfo", payload: { deflated_sharpe: 1.21 } }
];

export const fallbackPopulation: PopulationResponse = {
  total: 412,
  paper: 9,
  killed: 403,
  by_origin: { seed: 16, mutation: 261, wildcard: 118, pine: 17 },
  by_lane: { seed: 16, exploit: 261, explore: 118, pine: 17 },
  kill_rate: 0.978,
  graveyard: [
    { version_id: "g1", name: "Trend momentum × RSI fade", origin: "wildcard", kill_reason: "min_trades", deflated_sharpe: 0.71 },
    { version_id: "g2", name: "Funding carry · wide", origin: "mutation", kill_reason: "pbo,holdout", deflated_sharpe: 0.42 },
    { version_id: "g3", name: "Oversold mean reversion · +filter", origin: "mutation", kill_reason: "folds_positive", deflated_sharpe: 0.28 },
    { version_id: "g4", name: "Wildcard feature combo", origin: "wildcard", kill_reason: "max_drawdown", deflated_sharpe: 0.11 },
    { version_id: "g5", name: "RSI reversal (pine)", origin: "pine", kill_reason: "holdout", deflated_sharpe: -0.04 }
  ]
};

export const fallbackCohort: CohortSummaryResponse = {
  cohort_id: "demo-cohort",
  seed: 7,
  generated: 120,
  invalid: 0,
  killed: 113,
  passed: 7,
  kill_rate: 0.9417,
  lanes: { seed: 4, exploit: 81, explore: 35, pine: 0 },
  pine_imported: 0,
  survivors: [
    { version_id: "s1", name: "Trend momentum × Cross-asset", origin: "wildcard", lane: "explore", deflated_sharpe: 2.43, oos_return_pct: 18.82, passed: true, reasons: [] },
    { version_id: "s2", name: "Oversold mean reversion × Funding", origin: "wildcard", lane: "explore", deflated_sharpe: 2.19, oos_return_pct: 16.98, passed: true, reasons: [] },
    { version_id: "s3", name: "Funding-pressure carry · derisk", origin: "mutation", lane: "exploit", deflated_sharpe: 1.64, oos_return_pct: 11.4, passed: true, reasons: [] },
    { version_id: "s4", name: "Trend-confirmed momentum", origin: "seed", lane: "seed", deflated_sharpe: 1.38, oos_return_pct: 9.2, passed: true, reasons: [] }
  ],
  graveyard: [
    { version_id: "k1", name: "Trend momentum × RSI", origin: "wildcard", lane: "explore", deflated_sharpe: 0.74, oos_return_pct: 5.1, passed: false, reasons: ["min_trades"] },
    { version_id: "k2", name: "Cross-asset breakout · wide", origin: "mutation", lane: "exploit", deflated_sharpe: 0.39, oos_return_pct: 3.0, passed: false, reasons: ["holdout"] },
    { version_id: "k3", name: "Wildcard feature combo", origin: "wildcard", lane: "explore", deflated_sharpe: -0.12, oos_return_pct: -1.4, passed: false, reasons: ["pbo", "folds_positive"] }
  ],
  pine_notes: []
};

export async function getPopulation(): Promise<PopulationResponse> {
  return (await getJson("/population", fallbackPopulation)).data;
}

// Returns the REAL paper portfolio. `demo` is true only when the engine is unreachable
// (and we fall back to the clearly-labelled demo). When the engine is reachable but has no
// paper track record yet, it returns the honest empty portfolio (demo:false, empty arrays).
export async function getPortfolio(): Promise<{ portfolio: PortfolioResponse; demo: boolean }> {
  const { data, demo } = await getJson("/portfolio", demoPortfolio);
  return { portfolio: demo ? demoPortfolio : data, demo };
}

export async function getLeaderboard(): Promise<LeaderboardResponse> {
  return (await getJson("/leaderboard", fallbackLeaderboard)).data;
}

export async function getStrategy(id: string): Promise<StrategyDetailResponse> {
  return (await getJson(`/strategies/${id}`, fallbackStrategy)).data;
}

export async function getRecommendations(): Promise<Recommendation[]> {
  const { data } = await getJson("/recommendations", { items: fallbackRecommendations });
  return data.items;
}

export async function getEvents(): Promise<Event[]> {
  const { data } = await getJson("/events", { events: fallbackEvents });
  return data.events;
}

// Live trading positions snapshot for the /live surface. Locally-typed against the shared
// contract (see components/live/contracts) until @cosmu/contracts-ts ships these. `demo` is
// true only when the engine is unreachable — never presented as armed or live.
const emptyPositions: PositionsResponse = {
  armed: false,
  mode: "paper",
  daily_loss: 0,
  caps: { per_strategy_cap: 250, global_cap: 1000, max_daily_loss: 100 },
  positions: []
};

export async function getLivePositions(): Promise<PositionsResponse & { demo: boolean }> {
  const { data, demo } = await getJson<PositionsResponse>("/live/positions", emptyPositions);
  return { ...(demo ? emptyPositions : data), demo };
}

