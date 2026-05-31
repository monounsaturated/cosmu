// module: product data adapter. Purpose: feed the four Cosmu surfaces from the generated engine contract with local fallback for build-safe QA. Invariants: no secrets in the browser and no hand-written server contract drift.

import type {
  Backtest,
  Event,
  LeaderboardResponse,
  PortfolioResponse,
  Recommendation,
  StrategyDetailResponse
} from "@cosmu/contracts-ts";

const baseUrl = process.env.ENGINE_API_URL;

async function getJson<T>(path: string, fallback: T): Promise<T> {
  if (!baseUrl) return fallback;
  try {
    const response = await fetch(`${baseUrl}${path}`, { next: { revalidate: 5 } });
    if (!response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

const equityCurve = Array.from({ length: 48 }, (_, index) => {
  const value = 100000 + index * 178 + Math.sin(index / 3) * 900 - Math.max(0, index - 35) * 60;
  return { ts: `T-${47 - index}`, value: Math.round(value) };
});

export const fallbackPortfolio: PortfolioResponse = {
  equity_curve: equityCurve,
  pnl_net: equityCurve[equityCurve.length - 1].value - 100000,
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

export function getPortfolio(): Promise<PortfolioResponse> {
  return getJson("/portfolio", fallbackPortfolio);
}

export function getLeaderboard(): Promise<LeaderboardResponse> {
  return getJson("/leaderboard", fallbackLeaderboard);
}

export function getStrategy(id: string): Promise<StrategyDetailResponse> {
  return getJson(`/strategies/${id}`, fallbackStrategy);
}

export async function getRecommendations(): Promise<Recommendation[]> {
  const response = await getJson("/recommendations", { items: fallbackRecommendations });
  return response.items;
}

export async function getEvents(): Promise<Event[]> {
  const response = await getJson("/events", { events: fallbackEvents });
  return response.events;
}

