import type {
  RealtimeStatusResponse,
  LeaderboardResponse,
  OverviewResponse,
  PopulationResponse,
  PortfolioSummaryResponse,
  StrategyDetailResponse,
} from "@cosmu/contracts-ts";
import { getJson, LIVE_TTL_S } from "./client";

// ── Structurally-empty typing fallbacks (no fabricated numbers, no fake rows) ────────────────

const emptyOverview: OverviewResponse = {
  equity_curve: [],
  pnl_net: 0,
  costs: [],
  live_enabled: false,
  opex_vs_alpha: 0
};

const emptyLeaderboard: LeaderboardResponse = { rows: [] };

const emptyPopulation: PopulationResponse = {
  total: 0,
  paper: 0,
  live: 0,
  killed: 0,
  by_origin: {},
  by_lane: {},
  kill_rate: 0,
  graveyard: []
};

const emptyStrategy: StrategyDetailResponse = {
  version_id: "",
  name: "",
  spec: {},
  generated_code: "",
  params: {},
  trades: [],
  backtests: [],
  notes_md: "",
  holdout: {}
};

export async function getOverview(): Promise<{ overview: OverviewResponse; connected: boolean }> {
  const { data, connected } = await getJson("/overview", emptyOverview);
  // getJson only swaps in the typed default on a FAILED fetch — a successful-but-partial engine response
  // passes through raw, so a non-null contract field can still arrive null. Coalesce the array fields the
  // hero derefs (matches the costs.ts data-layer pattern) so a partial /overview can't white-screen.
  return { overview: { ...data, equity_curve: data.equity_curve ?? [] }, connected };
}

// GET /portfolio/summary — the honest live-vs-sim money split (LIVE $ · Free · Invested · P&L). When
// nothing is routed live, the live_* fields are null and render "—" — never SIM capital labelled live.
const emptyPortfolioSummary: PortfolioSummaryResponse = {
  has_live: false,
  live_armed: false,
  live_mode: "sim",
  sim_equity: 0,
  sim_pnl_net: 0,
  live_equity: null,
  live_invested: null,
  live_free: null,
  live_pnl_net: null,
  live_unrealized: null,
  live_realized: null,
  live_global_cap: 0,
  positions_count_live: 0,
};

export async function getPortfolioSummary(): Promise<{ summary: PortfolioSummaryResponse; connected: boolean }> {
  const { data, connected } = await getJson("/portfolio/summary", emptyPortfolioSummary, LIVE_TTL_S);
  return { summary: data, connected };
}

export async function getLeaderboard(): Promise<{ leaderboard: LeaderboardResponse; connected: boolean }> {
  const { data, connected } = await getJson("/leaderboard", emptyLeaderboard);
  // Coalesce rows so every consumer (paper / strategies / research) can `.filter`/`.map` safely even if a
  // partial /leaderboard omits the array (see getOverview note).
  return { leaderboard: { ...data, rows: data.rows ?? [] }, connected };
}

// Realtime worker pulse (realtime-data-lane P3): drives the Strategies-page staleness badge. Honest
// fallback = the worker is OFF (the engine default) — never a fabricated freshness.
export async function getRealtimeStatus(): Promise<{ realtime: RealtimeStatusResponse; connected: boolean }> {
  const { data, connected } = await getJson("/realtime/status", {
    enabled: false,
    status: "off",
    stale_after_seconds: 300,
  } as RealtimeStatusResponse);
  return { realtime: data, connected };
}

export async function getStrategy(id: string): Promise<{ strategy: StrategyDetailResponse; connected: boolean }> {
  const { data, connected } = await getJson(`/strategies/${id}`, emptyStrategy);
  // The detail sheet derefs trades/backtests/holdout (.length, spread, Object.entries) — the contract types
  // them non-null but the engine can omit them. Coalesce here so a partial /strategies/:id can't crash the
  // sheet or the standalone page (the components also guard locally; this is the single-source belt).
  return {
    strategy: {
      ...data,
      trades: data.trades ?? [],
      backtests: data.backtests ?? [],
      holdout: data.holdout ?? {},
    },
    connected,
  };
}

export async function getPopulation(): Promise<{ population: PopulationResponse; connected: boolean }> {
  const { data, connected } = await getJson("/population", emptyPopulation);
  return { population: data, connected };
}
