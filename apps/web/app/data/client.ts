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

export type {
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
// Server-render must never HANG on a cold/slow engine (Railway cold-start can take many seconds).
// Guard: AbortSignal.timeout(SSR_TIMEOUT_MS) — a hung engine fails FAST → we render the honest
// empty/not-connected state in ≤5s instead of blocking the whole SSR until the platform timeout.
// Note: `next.revalidate` is intentionally omitted. layout.tsx sets `dynamic = "force-dynamic"`,
// which opts every route out of the Next.js data cache; a per-fetch revalidate would have no effect.
const SSR_TIMEOUT_MS = 5000;

export async function getJson<T>(path: string, empty: T): Promise<{ data: T; connected: boolean }> {
  if (!baseUrl) return { data: empty, connected: false };
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      signal: AbortSignal.timeout(SSR_TIMEOUT_MS),
      headers: apiSecret ? { "x-api-key": apiSecret } : undefined
    });
    if (!response.ok) return { data: empty, connected: false };
    return { data: (await response.json()) as T, connected: true };
  } catch {
    return { data: empty, connected: false };
  }
}
