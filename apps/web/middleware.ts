// module: the Edge middleware guarding the engine proxy — the FIRST gate in front of /api/engine/*. It is the
// web half of the two-tier money-path auth. DARK LAUNCH: it is a pure PASS-THROUGH unless the server-side
// OPERATOR_AUTH_ENFORCED env var is truthy, so merging + the automatic Vercel deploy changes ZERO behavior and
// can never lock the operator out.
//
// When enforcement is ON (operator has set the secrets and flipped the flag):
//   • a MONEY MUTATION (POST /api/engine/toggle/live, /live/launch, /live/defund, /live/liquidate, …) requires a
//     valid, unexpired, HMAC-signed `cosmu_op` cookie — else 401. This is what stops anyone with the public URL
//     from driving the money control plane.
//   • a READ requires same-origin (Origin/Referer) — else 403. A light bar against drive-by cross-site reads.
// The middleware NEVER touches the engine's API secret (that stays server-side in the Node route) — it runs in
// the Edge runtime and only decides pass / 401 / 403. The single source of truth for what counts as a money
// mutation is lib/money-routes.ts, shared with the proxy so the two can't drift.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { classifyEngineRequest, isAuthEnforced } from "@/lib/money-routes";
import { OP_COOKIE, verifyOperatorToken } from "@/lib/operator-session";

export const config = {
  // Only intercept the engine proxy — every other route (pages, assets) is untouched.
  matcher: ["/api/engine/:path*"],
};

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const enforced = isAuthEnforced(process.env.OPERATOR_AUTH_ENFORCED);

  // ── DARK LAUNCH FAST PATH: flag off → do nothing, byte-identical to no middleware at all. ──
  if (!enforced) return NextResponse.next();

  const verdict = classifyEngineRequest({
    enforced,
    method: req.method,
    enginePath: req.nextUrl.pathname, // e.g. /api/engine/toggle/live — normalized inside
    self: req.nextUrl.origin,
    origin: req.headers.get("origin"),
    referer: req.headers.get("referer"),
  });

  if (verdict.kind === "pass") return NextResponse.next();

  if (verdict.kind === "cross-origin") {
    return NextResponse.json({ detail: "cross-origin read blocked" }, { status: 403 });
  }

  // verdict.kind === "need-session" — a money mutation. Verify the operator session cookie's MAC + expiry.
  const token = req.cookies.get(OP_COOKIE)?.value;
  const ok = await verifyOperatorToken(token, process.env.OPERATOR_SESSION_SECRET);
  if (!ok) {
    return NextResponse.json(
      { detail: "operator session required — sign in to drive the money control plane" },
      { status: 401 },
    );
  }
  return NextResponse.next();
}
