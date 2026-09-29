// module: the engine auth proxy. Same-origin catch-all that forwards browser requests to the engine,
// injecting the shared secret (API_SECRET_KEY) server-side so it NEVER reaches the client. Client
// components call /api/engine/<path> via lib/engine.ts#engineFetch; this handler relays to
// ${API_BASE_URL}/<path> with the X-API-Key header. Liveness (/health) needs no secret on the engine,
// but we send it anyway — harmless and uniform. When the engine isn't configured we return an honest 503.

import { NextRequest } from "next/server";
import { isAuthEnforced, isMoneyMutation } from "@/lib/money-routes";
import { OP_COOKIE, verifyOperatorToken } from "@/lib/operator-session";

const BASE = process.env.API_BASE_URL;
const SECRET = process.env.API_SECRET_KEY;

// Don't cache control-plane calls — they must reflect live engine state.
export const dynamic = "force-dynamic";

// Run the proxy in cdg1 (Paris), co-located with the engine (Railway europe-west4) + its DB — so client-side
// reads (browser → this proxy → engine) don't cross the Atlantic. Matches the SSR region pin in app/layout.tsx.
export const preferredRegion = "cdg1";

async function relay(req: NextRequest, path: string[]): Promise<Response> {
  if (!BASE) {
    return Response.json({ detail: "engine not configured (API_BASE_URL unset)" }, { status: 503 });
  }
  const search = req.nextUrl.search; // preserve query string (e.g. ?symbol=BTCUSDT&limit=20)
  const enginePath = `/${path.join("/")}`; // engine-relative path (leading slash), matches lib/money-routes
  const target = `${BASE}/${path.join("/")}${search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (SECRET) headers.set("x-api-key", SECRET);

  // ── SECOND TIER (dark-launched behind OPERATOR_AUTH_ENFORCED) ──────────────────────────────────────────
  // When the flag is OFF this whole block is skipped → byte-identical to the prior proxy. When ON and the
  // request is a money mutation, re-verify the operator session server-side (defense in depth behind the Edge
  // middleware) and inject `x-operator: <OPERATOR_SECRET_KEY>` so the engine's two-tier check can require it.
  // A money mutation with the flag on but the operator secret unset is a MISCONFIGURATION we refuse (500)
  // rather than forward an under-authenticated money call.
  if (isAuthEnforced(process.env.OPERATOR_AUTH_ENFORCED) && isMoneyMutation(req.method, enginePath)) {
    const OPERATOR_SECRET = process.env.OPERATOR_SECRET_KEY;
    if (!OPERATOR_SECRET) {
      return Response.json(
        { detail: "money control plane misconfigured: OPERATOR_SECRET_KEY unset while enforcement is on" },
        { status: 500 },
      );
    }
    const ok = await verifyOperatorToken(req.cookies.get(OP_COOKIE)?.value, process.env.OPERATOR_SESSION_SECRET);
    if (!ok) {
      return Response.json({ detail: "operator session required" }, { status: 401 });
    }
    headers.set("x-operator", OPERATOR_SECRET);
  }

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const body = hasBody ? await req.text() : undefined;

  try {
    // Fail fast on a hung/cold engine so a client control-plane call settles (502) instead of hanging the
    // serverless function until its platform timeout. Mirrors lib/engine.ts#engineFetchTimeout as a backstop.
    const res = await fetch(target, { method: req.method, headers, body, cache: "no-store", signal: AbortSignal.timeout(9000) });
    // Pass the engine's body + status through untouched so honest empty/offline states survive.
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" }
    });
  } catch {
    return Response.json({ detail: "engine unreachable" }, { status: 502 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return relay(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  return relay(req, (await ctx.params).path);
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  return relay(req, (await ctx.params).path);
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  return relay(req, (await ctx.params).path);
}
