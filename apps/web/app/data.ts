// module: product data adapter. Purpose: feed every Cosmu surface from the generated engine
// contract. Invariants: no secrets in the browser; no hand-written server-contract drift; and —
// CRITICAL — NEVER fabricate a track record. There is no "demo" money state in the product.
//
// HONESTY MODEL: every fetch returns `{ data, connected }`.
//   - connected === false  -> the engine is unreachable (no API_BASE_URL, fetch failed, or non-OK).
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
  InboxQueueItem,
  InboxQueueResponse,
  InfraLine,
  LeaderboardResponse,
  LlmCallSummary,
  MemoryInsight,
  MemoryInsightsResponse,
  MindResponse,
  NewsEventRow,
  NewsIntelResponse,
  OverviewResponse,
  PopulationResponse,
  Recommendation,
  ScoreCategory,
  ScoreSourceRow,
  ScoresResponse,
  SettingsKeyRow,
  SettingsKeysResponse,
  Skill,
  SkillsResponse,
  SourceTrustResponse,
  SourceTrustRow,
  StrategyDetailResponse,
  VendorActual,
} from "@cosmu/contracts-ts";
import type { PositionsResponse, LiveVenuesResponse } from "@/components/live/contracts";
import { EMPTY_AUTONOMY_STATUS, type AutonomyStatus } from "./autonomy-contracts";

// Skills, memory insights, costs, and scoreboard types come from the generated @cosmu/contracts-ts
// (no hand-typed contract drift). Re-exported here so surfaces keep importing from data.ts.
export type {
  Skill,
  SkillsResponse,
  MemoryInsight,
  MemoryInsightsResponse,
  CostByCategory,
  CostPerStrategy,
  CostsResponse,
  InfraLine,
  LlmCallSummary,
  VendorActual,
  SourceTrustRow,
  SourceTrustResponse,
  NewsEventRow,
  NewsIntelResponse,
  InboxQueueItem,
  InboxQueueResponse,
  ScoreSourceRow,
  ScoreCategory,
  ScoresResponse,
  SettingsKeyRow,
  SettingsKeysResponse,
};

const baseUrl = process.env.API_BASE_URL;
// Shared secret for the engine's control-plane gate. Server-side only — this module is never bundled
// into the browser, so the secret stays on the server. Sent as X-API-Key on every engine call.
const apiSecret = process.env.API_SECRET_KEY;

// Whether an API_BASE_URL is configured at all. Surfaces use this to tell the operator EXACTLY
// what to set when the engine isn't connected (rather than implying a transient outage).
export const engineConfigured = Boolean(baseUrl);

// Honest engine reachability. Server-rendered surfaces fetch the REAL engine; when it is
// unreachable we return the structurally-empty fallback and `connected:false` so the UI can say
// "not connected" out loud. We never invent numbers.
async function getJson<T>(path: string, empty: T): Promise<{ data: T; connected: boolean }> {
  if (!baseUrl) return { data: empty, connected: false };
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      next: { revalidate: 5 },
      headers: apiSecret ? { "x-api-key": apiSecret } : undefined
    });
    if (!response.ok) return { data: empty, connected: false };
    return { data: (await response.json()) as T, connected: true };
  } catch {
    return { data: empty, connected: false };
  }
}

// ── Structurally-empty typing fallbacks (no fabricated numbers, no fake rows) ────────────────

const emptyOverview: OverviewResponse = {
  equity_curve: [],
  pnl_net: 0,
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

const emptyMind: MindResponse = {
  as_of: null,
  railguard: "The Mind reasons; it never funds or fires an order. The deterministic gate alone disposes.",
  consensus: "neutral",
  conviction: 0,
  agreement: 0,
  contested: false,
  narrative: "",
  stances: [],
  bull_case: [],
  bear_case: [],
  knows: [],
  learnings: {
    insights: [],
    ml_trained: false,
    ml_backend: "heuristic",
    ml_auroc: null,
    ml_labels: 0,
    dead_ends: 0,
    winners: 0,
    skills: 0,
    gate_rate: 0,
    gate_trend: [],
    gate_improving: false,
    regime_grid: [],
    regime_covered: 0,
    regime_total: 9
  }
};

const emptyPopulation: PopulationResponse = {
  total: 0,
  forward_test: 0,
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

const emptySkills: SkillsResponse = { skills: [] };

const emptyInsights: MemoryInsightsResponse = { insights: [] };

const emptyCosts: CostsResponse = {
  total_usd: 0,
  by_category: [],
  opex_vs_alpha: 0,
  per_strategy: [],
  infra_lines: [],
  llm_calls: { call_count: 0, total_cost: 0, by_task: {} },
  vendor_actuals: [],
};

const emptyPositions: PositionsResponse = {
  armed: false,
  mode: "sim",
  daily_loss: 0,
  caps: { per_strategy_cap: 0, global_cap: 0, max_daily_loss: 0 },
  positions: []
};

// ── Typed re-export for components that locally type against the shared contract ─────────────
export type { BrainResponse };

// ── Fetchers. Each returns `connected` so the surface can pick honest empty vs not-connected. ─

export async function getOverview(): Promise<{ overview: OverviewResponse; connected: boolean }> {
  const { data, connected } = await getJson("/overview", emptyOverview);
  return { overview: data, connected };
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

// GET /mind — the agent's standardized self-knowledge: what it KNOWS (sources + freshness), how it THINKS
// (the analyst panel + the debate's consensus), and what it has LEARNED. A reasoning surface only — the
// `railguard` field restates that it never moves money. Honest: a perspective with no data ABSTAINS.
export async function getMind(): Promise<{ mind: MindResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind", emptyMind);
  return { mind: data, connected };
}

export async function getRecommendations(): Promise<{ items: Recommendation[]; connected: boolean }> {
  const { data, connected } = await getJson("/recommendations", { items: [] as Recommendation[] });
  return { items: data.items, connected };
}

export async function getEvents(): Promise<{ events: Event[]; connected: boolean }> {
  const { data, connected } = await getJson("/events", { events: [] as Event[] });
  return { events: data.events, connected };
}

// GET /lab/inbox — the operator's queued natural-language strategy ideas (newest first). Each stays
// "queued" until a scan turns its brief into a typed, gated spec, then flips to "imported". Honest empty
// when nothing has been dropped yet; never fabricated.
const emptyInboxQueue: InboxQueueResponse = { items: [], inbox_dir: "" };

export async function getInboxQueue(): Promise<{ items: InboxQueueItem[]; connected: boolean }> {
  const { data, connected } = await getJson<InboxQueueResponse>("/lab/inbox", emptyInboxQueue);
  return { items: data.items, connected };
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
  // Normalize: a deployed engine on an older shape may omit the newer arrays (e.g. vendor_actuals),
  // which would crash prerender on `.length`. Coerce every array/object field to a safe default.
  const costs: CostsResponse = {
    ...emptyCosts,
    ...data,
    by_category: data.by_category ?? [],
    per_strategy: data.per_strategy ?? [],
    infra_lines: data.infra_lines ?? [],
    vendor_actuals: data.vendor_actuals ?? [],
    llm_calls: data.llm_calls ?? emptyCosts.llm_calls,
  };
  return { costs, connected };
}

// GET /autonomy/status — the command-center status of the autonomous machine the human oversees:
// running/paused, live on/off, cycles run, what it last did + will do next, and the last cycle's
// counts. `connected:false` renders an honest "machine status unknown" state — never a fake running
// machine. The deterministic Gate/scorer still disposes; this status only reports, never decides.
export async function getAutonomyStatus(): Promise<{ status: AutonomyStatus; connected: boolean }> {
  const { data, connected } = await getJson("/autonomy/status", EMPTY_AUTONOMY_STATUS);
  return { status: data, connected };
}

// Live trading positions snapshot for the /live surface. `connected:false` is shown as engine-
// offline — never presented as armed or live.
export async function getLivePositions(): Promise<PositionsResponse & { connected: boolean }> {
  const { data, connected } = await getJson<PositionsResponse>("/live/positions", emptyPositions);
  return { ...data, connected };
}

const emptyVenues: LiveVenuesResponse = { jurisdiction: "", global_cap: 0, total_deployed_usd: 0, venues: [] };

export async function getLiveVenues(): Promise<LiveVenuesResponse & { connected: boolean }> {
  const { data, connected } = await getJson<LiveVenuesResponse>("/live/venues", emptyVenues);
  return { ...data, connected };
}

// GET /intelligence — system intelligence: "is the machine getting smarter?" Strategy funnel,
// gate efficiency trend, memory depth, regime coverage, data freshness, tick history, lineage.
export interface FunnelStats {
  authored: number;
  screened: number;
  gate_passed: number;
  funded: number;
  live: number;
  killed: number;
}

export interface GateEfficiency {
  current: number;
  trend: number[];
  improving: boolean;
}

export interface MemoryDepth {
  dead_ends: number;
  winners: number;
  skills: number;
  total: number;
}

export interface RegimeCell {
  regime: string;
  trend: string;
  vol: string;
  strategies: number;
}

export interface RegimeCoverage {
  grid: RegimeCell[];
  covered: number;
  total: number;
  by_label: Record<string, number>;
}

export interface DataSource {
  source: string;
  last_at: string | null;
  points: number;
}

export interface TickDetail {
  authored: number;
  passed: number;
  funded: number;
}

export interface TickStats {
  total: number;
  last_at: string | null;
  avg_survivors_per_tick: number;
  total_authored: number;
  total_survivors: number;
  recent: TickDetail[];
}

export interface LineageEntry {
  origin?: string;
  operator?: string;
  total: number;
  passed: number;
  rate: number;
}

export interface LineageStats {
  by_origin: LineageEntry[];
  by_operator: LineageEntry[];
}

export interface IntelligenceResponse {
  funnel: FunnelStats;
  gate_efficiency: GateEfficiency;
  memory: MemoryDepth;
  regime_coverage: RegimeCoverage;
  data_freshness: DataSource[];
  ticks: TickStats;
  lineage: LineageStats;
}

const emptyIntelligence: IntelligenceResponse = {
  funnel: { authored: 0, screened: 0, gate_passed: 0, funded: 0, live: 0, killed: 0 },
  gate_efficiency: { current: 0, trend: [], improving: false },
  memory: { dead_ends: 0, winners: 0, skills: 0, total: 0 },
  regime_coverage: { grid: [], covered: 0, total: 9, by_label: {} },
  data_freshness: [],
  ticks: { total: 0, last_at: null, avg_survivors_per_tick: 0, total_authored: 0, total_survivors: 0, recent: [] },
  lineage: { by_origin: [], by_operator: [] },
};

export async function getIntelligence(): Promise<{ intelligence: IntelligenceResponse; connected: boolean }> {
  const { data, connected } = await getJson("/intelligence", emptyIntelligence);
  return { intelligence: data, connected };
}

// Source-trust scoreboard: one row per registered data source, freshness × gate contribution.
// Honest: sources with no data show trust_score=0, status="no data". Never fabricated.
const emptySourceTrust: SourceTrustResponse = { as_of: "", rows: [] };

export async function getSourceTrust(): Promise<{ trust: SourceTrustResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind/source-trust", emptySourceTrust);
  return { trust: data, connected };
}

// GET /scores — the scores cockpit: per-source + composite INDEX scores grouped by category (crypto ·
// social · macro · OSINT · metals/forex), each with freshness and a plain-language review. Honest: a
// category/source with no data shows index=null, connected=false; a key-gated source with no key on the
// engine shows disabled=true so the UI greys it out. Never fabricated.
const emptyScores: ScoresResponse = {
  as_of: "",
  composite_index: null,
  composite_status: "offline",
  composite_review: "",
  categories: []
};

export async function getScores(): Promise<{ scores: ScoresResponse; connected: boolean }> {
  const { data, connected } = await getJson("/scores", emptyScores);
  return { scores: data, connected };
}

// News/intel panel: recent scored news events (typed, dated, point-in-time).
// Honest empty state when no news has been ingested yet.
const emptyNewsIntel: NewsIntelResponse = { symbol: "BTCUSDT", events: [] };

export async function getNewsIntel(symbol = "BTCUSDT", limit = 20): Promise<{ intel: NewsIntelResponse; connected: boolean }> {
  const { data, connected } = await getJson(
    `/mind/news-intel?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
    emptyNewsIntel
  );
  return { intel: data, connected };
}

// ── Verdict ledger: parsed phase0-*-verdict.md research history ──────────────────────────────────

export interface VerdictRow {
  slug: string;
  thesis: string;
  id: string;
  date: string;
  status: "PASS" | "FAIL" | "INSUFFICIENT-DATA" | "DATA-BLOCKED";
  deflated_sharpe: number | null;
  trades: number | null;
  cost_ratio: number | null;
  reason: string;
}

export interface VerdictsResponse {
  rows: VerdictRow[];
}

const emptyVerdicts: VerdictsResponse = { rows: [] };

// GET /verdicts — static research history parsed from docs/reports/phase0-*-verdict.md.
// Returns empty rows when engine is offline or docs are not deployed alongside the engine.
export async function getVerdicts(): Promise<{ verdicts: VerdictsResponse; connected: boolean }> {
  const { data, connected } = await getJson<VerdictsResponse>("/verdicts", emptyVerdicts);
  return { verdicts: { rows: data.rows ?? [] }, connected };
}

// GET /settings/keys — the read-only key inventory for Settings → Keys: which provider keys are
// configured on the engine and what each unlocks. SECURITY: the engine returns a boolean `configured`
// per key, NEVER the value. Honest empty/offline when the engine is unreachable.
const emptySettingsKeys: SettingsKeysResponse = { rows: [] };

export async function getSettingsKeys(): Promise<{ keys: SettingsKeyRow[]; connected: boolean }> {
  const { data, connected } = await getJson<SettingsKeysResponse>("/settings/keys", emptySettingsKeys);
  return { keys: data.rows, connected };
}

export interface VerdictItem {
  id: string;
  name: string;
  verdict: string;
  reason: string;
}

const emptyVerdicts: { verdicts: VerdictItem[] } = { verdicts: [] };

export async function getVerdicts(): Promise<{ verdicts: VerdictItem[]; connected: boolean }> {
  const { data, connected } = await getJson<{ verdicts: VerdictItem[] }>("/verdicts", emptyVerdicts);
  return { verdicts: Array.isArray(data.verdicts) ? data.verdicts : [], connected };
}
