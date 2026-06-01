// module: product data adapter. Purpose: feed every Cosmu surface from the generated engine
// contract. Invariants: no secrets in the browser; no hand-written server-contract drift; and —
// CRITICAL — NEVER fabricate a track record. There is no "demo" money state in the product.
//
// HONESTY MODEL: every fetch returns `{ data, connected }`.
//   - connected === false  -> the engine is unreachable (no ENGINE_API_URL, fetch failed, or non-OK).
//                             The UI renders an HONEST "Engine not connected" state, never numbers.
//   - connected === true   -> real engine data. It may still be structurally EMPTY (e.g. no
//                             survivors yet); the UI renders an honest "nothing yet" empty state.
// The only fallbacks below are STRUCTURALLY-EMPTY objects, kept solely so the types resolve and
// the page can render its empty state. They contain ZERO fabricated numbers and ZERO fake rows.

import type {
  BrainResponse,
  CostByCategory,
  CostPerStrategy,
  CostsResponse,
  Event,
  LeaderboardResponse,
  MemoryInsight,
  MemoryInsightsResponse,
  PopulationResponse,
  PortfolioResponse,
  Recommendation,
  Skill,
  SkillsResponse,
  StrategyDetailResponse
} from "@cosmu/contracts-ts";
import type { PositionsResponse } from "@/components/live/contracts";

// Skills, memory insights, and costs come from the generated @cosmu/contracts-ts (no hand-typed
// contract drift). Re-exported here so the surfaces that consume them keep importing from data.ts.
export type {
  Skill,
  SkillsResponse,
  MemoryInsight,
  MemoryInsightsResponse,
  CostByCategory,
  CostPerStrategy,
  CostsResponse
};

const baseUrl = process.env.ENGINE_API_URL;

// Whether an ENGINE_API_URL is configured at all. Surfaces use this to tell the operator EXACTLY
// what to set when the engine isn't connected (rather than implying a transient outage).
export const engineConfigured = Boolean(baseUrl);

// Honest engine reachability. Server-rendered surfaces fetch the REAL engine; when it is
// unreachable we return the structurally-empty fallback and `connected:false` so the UI can say
// "not connected" out loud. We never invent numbers.
async function getJson<T>(path: string, empty: T): Promise<{ data: T; connected: boolean }> {
  if (!baseUrl) return { data: empty, connected: false };
  try {
    const response = await fetch(`${baseUrl}${path}`, { next: { revalidate: 5 } });
    if (!response.ok) return { data: empty, connected: false };
    return { data: (await response.json()) as T, connected: true };
  } catch {
    return { data: empty, connected: false };
  }
}

// ── Structurally-empty typing fallbacks (no fabricated numbers, no fake rows) ────────────────

const emptyPortfolio: PortfolioResponse = {
  equity_curve: [],
  pnl_net: 0,
  allocation: [],
  costs: [],
  live_enabled: false,
  opex_vs_alpha: 0
};

const emptyLeaderboard: LeaderboardResponse = { rows: [] };

const emptyBrain: BrainResponse = {
  llm: "off",
  gated: { generated: 0, passed: 0, killed: 0, kill_rate: 0 },
  survivors: [],
  graveyard: [],
  sources: [],
  tools: [],
  regime: { label: "unknown", vol_bucket: "—", trend: "flat" },
  survival_ranking: []
};

const emptyPopulation: PopulationResponse = {
  total: 0,
  paper: 0,
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

const emptySkills: SkillsResponse = { skills: [] };

const emptyInsights: MemoryInsightsResponse = { insights: [] };

const emptyCosts: CostsResponse = {
  total_usd: 0,
  by_category: [],
  opex_vs_alpha: 0,
  per_strategy: []
};

const emptyPositions: PositionsResponse = {
  armed: false,
  mode: "paper",
  daily_loss: 0,
  caps: { per_strategy_cap: 0, global_cap: 0, max_daily_loss: 0 },
  positions: []
};

// ── Typed re-export for components that locally type against the shared contract ─────────────
export type { BrainResponse };

// ── Fetchers. Each returns `connected` so the surface can pick honest empty vs not-connected. ─

export async function getPortfolio(): Promise<{ portfolio: PortfolioResponse; connected: boolean }> {
  const { data, connected } = await getJson("/portfolio", emptyPortfolio);
  return { portfolio: data, connected };
}

export async function getLeaderboard(): Promise<{ leaderboard: LeaderboardResponse; connected: boolean }> {
  const { data, connected } = await getJson("/leaderboard", emptyLeaderboard);
  return { leaderboard: data, connected };
}

export async function getStrategy(id: string): Promise<{ strategy: StrategyDetailResponse; connected: boolean }> {
  const { data, connected } = await getJson(`/strategies/${id}`, emptyStrategy);
  return { strategy: data, connected };
}

// GET /research/brain — the research brain: LLM on/off, the deterministic gate funnel, survivors,
// graveyard, regime, data sources, bus tools, and the survival-model ranking. The ranking only
// ORDERS the validation queue (which candidate to compute first) — it never vetoes.
export async function getBrain(): Promise<{ brain: BrainResponse; connected: boolean }> {
  const { data, connected } = await getJson("/research/brain", emptyBrain);
  return { brain: data, connected };
}

export async function getPopulation(): Promise<{ population: PopulationResponse; connected: boolean }> {
  const { data, connected } = await getJson("/population", emptyPopulation);
  return { population: data, connected };
}

export async function getRecommendations(): Promise<{ items: Recommendation[]; connected: boolean }> {
  const { data, connected } = await getJson("/recommendations", { items: [] as Recommendation[] });
  return { items: data.items, connected };
}

export async function getEvents(): Promise<{ events: Event[]; connected: boolean }> {
  const { data, connected } = await getJson("/events", { events: [] as Event[] });
  return { events: data.events, connected };
}

// GET /skills — distilled skill recipes the brain has learned (the flywheel made visible). Empty
// when the brain hasn't distilled any reusable recipe yet.
export async function getSkills(): Promise<{ skills: Skill[]; connected: boolean }> {
  const { data, connected } = await getJson("/skills", emptySkills);
  return { skills: data.skills, connected };
}

// GET /memory/insights — dead-ends the brain avoids and winner patterns it leans into.
export async function getInsights(): Promise<{ insights: MemoryInsight[]; connected: boolean }> {
  const { data, connected } = await getJson("/memory/insights", emptyInsights);
  return { insights: data.insights, connected };
}

// GET /costs — the dedicated ROI view (opex vs alpha, spend by category, per-strategy attribution).
export async function getCosts(): Promise<{ costs: CostsResponse; connected: boolean }> {
  const { data, connected } = await getJson("/costs", emptyCosts);
  return { costs: data, connected };
}

// Live trading positions snapshot for the /live surface. `connected:false` is shown as engine-
// offline — never presented as armed or live.
export async function getLivePositions(): Promise<PositionsResponse & { connected: boolean }> {
  const { data, connected } = await getJson<PositionsResponse>("/live/positions", emptyPositions);
  return { ...data, connected };
}
