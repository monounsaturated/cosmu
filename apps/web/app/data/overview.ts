import type {
  RealtimeStatusResponse,
  LeaderboardResponse,
  OverviewResponse,
  PopulationResponse,
  StrategyDetailResponse,
} from "@cosmu/contracts-ts";
import { getJson } from "./client";

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
  return { overview: data, connected };
}

export async function getLeaderboard(): Promise<{ leaderboard: LeaderboardResponse; connected: boolean }> {
  const { data, connected } = await getJson("/leaderboard", emptyLeaderboard);
  return { leaderboard: data, connected };
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
  return { strategy: data, connected };
}

export async function getPopulation(): Promise<{ population: PopulationResponse; connected: boolean }> {
  const { data, connected } = await getJson("/population", emptyPopulation);
  return { population: data, connected };
}
