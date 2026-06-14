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

import { unstable_cache } from "next/cache";

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
const SSR_TIMEOUT_MS = 5000;

// SPEED: layout.tsx keeps every route `force-dynamic` (rendered per-request — no build-time prerender
// hang, no baked "not connected"). But the SLOW part — the ~2s engine call — is wrapped in the Next
// data cache via unstable_cache, so repeat navigation and concurrent loads within the TTL reuse one
// response instead of re-hitting the engine every time. Only SUCCESSFUL reads are cached — the inner
// fn THROWS on failure, so a transient outage is never cached as a sticky "not connected".
//
// Two TTLs: most surfaces run on crons and tolerate ~15s staleness (ENGINE_TTL_S); the live-money /
// safety reads (positions, venues, portfolio split, rules, autonomy) want near-real-time, so they pass
// LIVE_TTL_S — short enough that you never act on a stale money figure, long enough to coalesce the
// burst of parallel calls in one page load. Both tunable via env.
export const ENGINE_TTL_S = Number(process.env.WEB_ENGINE_TTL_S ?? 15);
export const LIVE_TTL_S = Number(process.env.WEB_LIVE_TTL_S ?? 3);

// One cached fetcher per distinct TTL (unstable_cache fixes `revalidate` at wrap time, so we memoize a
// wrapper per TTL value). `path` is the cache-key arg; the TTL is in keyParts so entries never collide.
const cachedByTtl = new Map<number, (path: string) => Promise<unknown>>();
function engineFetcher(revalidate: number): (path: string) => Promise<unknown> {
  let fn = cachedByTtl.get(revalidate);
  if (!fn) {
    fn = unstable_cache(
      async (path: string): Promise<unknown> => {
        const response = await fetch(`${baseUrl}${path}`, {
          signal: AbortSignal.timeout(SSR_TIMEOUT_MS),
          headers: apiSecret ? { "x-api-key": apiSecret } : undefined,
        });
        if (!response.ok) throw new Error(`engine ${path} -> ${response.status}`);
        return response.json();
      },
      ["engine-read", String(revalidate)],
      { revalidate },
    );
    cachedByTtl.set(revalidate, fn);
  }
  return fn;
}

export async function getJson<T>(
  path: string,
  empty: T,
  revalidate: number = ENGINE_TTL_S,
): Promise<{ data: T; connected: boolean }> {
  if (!baseUrl) return { data: empty, connected: false };
  try {
    return { data: (await engineFetcher(revalidate)(path)) as T, connected: true };
  } catch {
    return { data: empty, connected: false };
  }
}
