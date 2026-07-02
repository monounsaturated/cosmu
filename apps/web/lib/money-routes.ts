// module: the SINGLE SOURCE OF TRUTH for which engine control-plane routes move (or arm) real money.
// Imported by BOTH the Edge middleware (middleware.ts) AND the server proxy (app/api/engine/[...path]/route.ts)
// so the two enforcement points can NEVER drift. Zero dependencies (pure string logic) so it runs unchanged in
// the Edge runtime, the Node route runtime, and a plain `node --test` unit run.
//
// SECURITY MODEL — DENY BY DEFAULT: `isMoneyMutation` returns true when a request matches a KNOWN money-
// mutation pattern AFTER anti-evasion normalization. The middleware/route treat a money mutation as the guarded
// class (operator session required when enforcement is ON). Everything else — reads, and the pure reduce-only
// SAFETY exits (kill-switch, order-cancel) that must ALWAYS route even without a session — is not gated here.
//
// The patterns are grepped from the real engine routers (apps/engine/cosmu/api/routers/{toggle,live,ops}.py):
//   POST /toggle/live            — arm / disarm live (the master live switch)
//   POST /live/activate          — arm a strategy live
//   POST /live/launch            — launch live capital
//   POST /live/defund            — defund (routes a real exit, then zeroes the book)
//   POST /live/liquidate         — liquidate-all / per-strategy stop (real capital move)
//   POST /live/rules             — set the live caps / daily-loss blocker (governs real money)
//   POST /live/jurisdiction      — set the operating jurisdiction (which venues may move real money)
//   POST /ops/breaker/rearm      — clear the circuit-breaker safety latch so live may be re-enabled
// EXCLUDED (pure reduce-only safety — must route even with no session, so NOT a guarded money mutation):
//   POST /ops/killswitch, POST /live/orders/{id}/cancel  (they can only ever REDUCE exposure).

// The engine path (no /api/engine prefix, leading slash, no query, no trailing slash) → whether it's a guarded
// money mutation. A matcher is a concrete engine path OR a {prefix} for path-parameter routes (none of the
// money routes take a path param today, but the shape is future-proof and explicit).
export const MONEY_MUTATION_PATHS: ReadonlySet<string> = new Set([
  "/toggle/live",
  "/live/activate",
  "/live/launch",
  "/live/defund",
  "/live/liquidate",
  "/live/rules",
  "/live/jurisdiction",
  "/ops/breaker/rearm",
]);

// Human-readable list for tests / audits (kept in lockstep with the set above).
export const MONEY_MUTATION_MATCHERS: readonly string[] = Array.from(MONEY_MUTATION_PATHS);

// Only mutating verbs can move money. A GET/HEAD/OPTIONS to any of the paths above is never a mutation.
const MUTATION_METHODS: ReadonlySet<string> = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// decodeAll — repeatedly percent-decode until stable so a double/triple-encoded segment (%252e, %25%32%65…)
// collapses to its real character before we match. Bounded to a few passes (a real path never nests deeper);
// a malformed sequence that throws is treated as "no further decode" (we keep the last good value).
function decodeAll(s: string): string {
  let prev = s;
  for (let i = 0; i < 5; i++) {
    let next: string;
    try {
      next = decodeURIComponent(prev);
    } catch {
      return prev; // malformed %xx — stop decoding, match on what we have
    }
    if (next === prev) return next;
    prev = next;
  }
  return prev;
}

// normalizeEnginePath — turn any raw engine-relative path (possibly attacker-shaped) into the ONE canonical
// form the matcher set is keyed on. Anti-evasion, in order:
//   • strip a leading /api/engine (defensive — callers should pass the engine path, but accept the proxy path)
//   • fully percent-decode (defeats %2e / %2f / %2E and multi-encoding)
//   • lowercase (routes are case-insensitive to us; the engine paths are all lowercase)
//   • backslash → forward slash (some clients send \ ; Next/undici may not normalize it)
//   • collapse repeated slashes (`//live//launch` → `/live/launch`)
//   • resolve `.`/`..` segments (defeats `/live/../live/launch` and `/live/./launch`)
//   • drop a trailing slash (except the root)
//   • ensure a single leading slash
export function normalizeEnginePath(raw: string): string {
  let p = raw ?? "";
  // Cut a query string / fragment if one slipped in.
  const q = p.search(/[?#]/);
  if (q !== -1) p = p.slice(0, q);
  p = decodeAll(p);
  p = p.toLowerCase();
  p = p.replace(/\\/g, "/");
  // Strip an accidental proxy prefix so both `/api/engine/toggle/live` and `/toggle/live` normalize the same.
  p = p.replace(/^\/*api\/engine(?=\/|$)/, "");
  // Split, dropping empty (collapses // and leading/trailing slashes) and resolving . / ..
  const out: string[] = [];
  for (const seg of p.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      out.pop();
      continue;
    }
    out.push(seg);
  }
  return "/" + out.join("/");
}

// isMoneyMutation — the deny-by-default decision used by the middleware and the proxy. True ONLY when the
// (normalized path, mutating method) pair matches a known money-mutation route. Anything unknown is treated as
// NOT a money mutation (it still flows through the normal x-api-key path) — the guard here is additive, never a
// new way to block a legitimate read.
export function isMoneyMutation(method: string, rawPath: string): boolean {
  if (!MUTATION_METHODS.has((method ?? "").toUpperCase())) return false;
  return MONEY_MUTATION_PATHS.has(normalizeEnginePath(rawPath));
}

// isAuthEnforced — the single dark-launch switch. Reads the server-side OPERATOR_AUTH_ENFORCED env var. OFF by
// default: only the exact truthy strings below flip it on, so an unset/blank/"false"/"0" var (the deploy
// default) leaves EVERY new enforcement path a no-op — byte-identical to pre-change behavior.
export function isAuthEnforced(raw: string | undefined | null): boolean {
  const v = (raw ?? "").trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

// Same-origin check for READS when enforcement is on: a browser navigation/fetch to our own site sends an
// Origin or Referer whose origin equals the request's own origin. A cross-site caller (someone hot-linking the
// public engine proxy from another page) fails this. Absent BOTH headers we allow (server-to-server, curl, and
// same-origin top-level GETs legitimately omit Origin) — the money MUTATIONS are protected by the cookie, not
// by this; this only raises the bar on drive-by reads. `self` is the request's own origin (e.g. https://app…).
export function isSameOrigin(self: string, origin: string | null, referer: string | null): boolean {
  const candidate = origin ?? referer;
  if (!candidate) return true; // no cross-site signal present → don't block (mutations still need the cookie)
  try {
    return new URL(candidate).origin === self;
  } catch {
    return false; // a malformed Origin/Referer is treated as cross-site
  }
}

// The middleware's pure verdict for a request to /api/engine/*, EXCLUDING the cookie MAC check (which needs
// async Web Crypto and lives in middleware.ts). Splitting it out keeps a dependency-free, synchronously
// testable core — in particular the dark-launch invariant "flag off → PASS" is unit-tested here with no
// next/server import.
export type MiddlewareVerdict =
  | { kind: "pass" } // let the request through untouched (dark default, or an allowed read)
  | { kind: "need-session" } // a money mutation — middleware must verify the cosmu_op cookie (401 if bad)
  | { kind: "cross-origin" }; // a read that failed the same-origin check (403)

export function classifyEngineRequest(args: {
  enforced: boolean;
  method: string;
  enginePath: string; // path WITH or without the /api/engine prefix — normalized inside
  self: string;
  origin: string | null;
  referer: string | null;
}): MiddlewareVerdict {
  if (!args.enforced) return { kind: "pass" }; // ── DARK LAUNCH: flag off → identical to today ──
  if (isMoneyMutation(args.method, args.enginePath)) return { kind: "need-session" };
  return isSameOrigin(args.self, args.origin, args.referer) ? { kind: "pass" } : { kind: "cross-origin" };
}
