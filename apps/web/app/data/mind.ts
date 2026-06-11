import type {
  CredibilityResponse,
  MindResponse,
  NewsIntelResponse,
  ScoresResponse,
  SourceTrustResponse,
} from "@cosmu/contracts-ts";
import { getJson } from "./client";

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

// Source-trust scoreboard: one row per registered data source, freshness × gate contribution.
// Honest: sources with no data show trust_score=0, status="no data". Never fabricated.
const emptySourceTrust: SourceTrustResponse = { as_of: "", rows: [] };

// Source credibility (voice scoreboard): one flat row per pre-registered voice, skill DESC NULLS LAST.
// Honest: an untested voice carries null metrics (untested ≠ unskilled); empty panel = empty rows.
const emptyCredibility: CredibilityResponse = { as_of: null, panel_size: 0, rows: [] };

const emptyScores: ScoresResponse = {
  as_of: "",
  composite_index: null,
  composite_status: "offline",
  composite_review: "",
  categories: []
};

// News/intel panel: recent scored news events (typed, dated, point-in-time).
// Honest empty state when no news has been ingested yet.
const emptyNewsIntel: NewsIntelResponse = { symbol: "BTCUSDT", events: [] };

// GET /mind — the agent's standardized self-knowledge: what it KNOWS (sources + freshness), how it THINKS
// (the analyst panel + the debate's consensus), and what it has LEARNED. A reasoning surface only — the
// `railguard` field restates that it never moves money. Honest: a perspective with no data ABSTAINS.
export async function getMind(): Promise<{ mind: MindResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind", emptyMind);
  return { mind: data, connected };
}

export async function getSourceTrust(): Promise<{ trust: SourceTrustResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind/source-trust", emptySourceTrust);
  return { trust: data, connected };
}

// GET /mind/credibility — the SOURCE SCOREBOARD: every followed voice's resolved-call record (Brier skill
// vs the base rate, calibration, primacy). Honest: null metrics mean UNTESTED — the UI renders an em-dash,
// never a fabricated zero. Voices are pre-registered in apps/engine/cosmu/config/voices.py.
export async function getVoiceCredibility(): Promise<{ credibility: CredibilityResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind/credibility", emptyCredibility);
  return { credibility: data, connected };
}

// GET /scores — the scores cockpit: per-source + composite INDEX scores grouped by category (crypto ·
// social · macro · OSINT · metals/forex), each with freshness and a plain-language review. Honest: a
// category/source with no data shows index=null, connected=false; a key-gated source with no key on the
// engine shows disabled=true so the UI greys it out. Never fabricated.
export async function getScores(): Promise<{ scores: ScoresResponse; connected: boolean }> {
  const { data, connected } = await getJson("/scores", emptyScores);
  return { scores: data, connected };
}

export async function getNewsIntel(symbol = "BTCUSDT", limit = 20): Promise<{ intel: NewsIntelResponse; connected: boolean }> {
  const { data, connected } = await getJson(
    `/mind/news-intel?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
    emptyNewsIntel
  );
  return { intel: data, connected };
}
