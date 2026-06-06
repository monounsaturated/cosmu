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
