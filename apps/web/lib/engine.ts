// module: the client-side engine adapter. CRITICAL SECURITY INVARIANT — the engine's shared secret
// (API_SECRET_KEY) must NEVER reach the browser. So client components never call the engine directly;
// they call the same-origin Next.js proxy at /api/engine/* (see app/api/engine/[...path]/route.ts),
// which runs on the server and injects the secret header before forwarding. This also sidesteps CORS.
//
// `ENGINE_CONFIGURED` preserves the old "is the engine wired?" signal (components early-return and render
// an honest not-connected state when false). It reads the PUBLIC base-url flag only — never a secret.

export const ENGINE_CONFIGURED = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL);

// engineFetch — call an engine path through the server proxy. Pass the engine-relative path (e.g.
// "/research/gate"); the proxy forwards method, body, and query to ${API_BASE_URL}${path} with auth.
export function engineFetch(path: string, init?: RequestInit): Promise<Response> {
  const p = path.startsWith("/") ? path : `/${path}`;
  return fetch(`/api/engine${p}`, init);
}

// ── client-side GET cache ────────────────────────────────────────────────────────────────────────
// The proxy route is force-dynamic/no-store (control-plane must reflect live state), so every client GET is a
// fresh ~2s engine round-trip. For READ-ONLY detail reads (the strategy sheet) that's wasteful: re-opening the
// same Version re-fetched from scratch, and the first open always paid the full latency. This is a small
// in-memory cache + in-flight dedup: re-reads within ttlMs (and concurrent reads of the same path) reuse one
// response, and `enginePrefetch` on row hover warms it so the click feels instant. Failures are NEVER cached
// (callers fall to their honest error state); the cache is per-tab and evaporates on reload — never persisted.
type _CacheEntry = { at: number; data: unknown };
const _getCache = new Map<string, _CacheEntry>();
const _inflight = new Map<string, Promise<unknown>>();
// Bound the cache so a long session hovering hundreds of rows can't grow it without limit. Map preserves
// insertion order, so deleting the first key evicts the oldest entry (a simple LRU-ish cap, no library).
const _CACHE_MAX = 100;

// enginePeek — synchronous cache hit (or undefined). Lets a component render cached detail with NO loading
// flash, then optionally revalidate. ttlMs default 30s matches engineGetJson.
export function enginePeek<T>(path: string, ttlMs = 30_000): T | undefined {
  const hit = _getCache.get(path);
  return hit && Date.now() - hit.at < ttlMs ? (hit.data as T) : undefined;
}

// engineGetJson — GET + parse JSON through the proxy, with the short in-memory cache + in-flight dedup above.
// Throws on non-OK so callers keep their honest error state. Use for idempotent reads only (never mutations).
export async function engineGetJson<T>(path: string, ttlMs = 30_000): Promise<T> {
  const cached = enginePeek<T>(path, ttlMs);
  if (cached !== undefined) return cached;
  let inf = _inflight.get(path) as Promise<T> | undefined;
  if (!inf) {
    inf = engineFetch(path)
      .then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (_getCache.size >= _CACHE_MAX) {
          const oldest = _getCache.keys().next().value;
          if (oldest !== undefined) _getCache.delete(oldest);
        }
        _getCache.set(path, { at: Date.now(), data });
        return data;
      })
      .finally(() => {
        _inflight.delete(path);
      });
    _inflight.set(path, inf);
  }
  return inf;
}

// enginePrefetch — best-effort cache warm (e.g. on row hover) so the subsequent open is instant. Ignores errors.
export function enginePrefetch(path: string, ttlMs = 30_000): void {
  if (enginePeek(path, ttlMs) !== undefined || _inflight.has(path)) return;
  void engineGetJson(path, ttlMs).catch(() => {});
}

// engineFetchTimeout — engineFetch with a built-in AbortController so a hung/slow engine can NEVER leave a
// control stuck "pending" (greyed) forever. It aborts after `ms` (default 8s), so the promise ALWAYS settles
// and callers can reliably clear their per-control in-flight flag (in `finally`, or via useTransition). This
// is the going-forward primitive for any mutating control; pair it with a try/catch that surfaces a note.
export async function engineFetchTimeout(path: string, init: RequestInit = {}, ms = 8000): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await engineFetch(path, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}
