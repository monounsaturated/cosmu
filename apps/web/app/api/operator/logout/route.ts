// module: operator LOGOUT — clear the `cosmu_op` session cookie so the money control plane locks again. Always
// succeeds (idempotent): clearing a cookie that isn't there is a no-op. Harmless while the dark-launch flag is
// off. No secret needed — clearing a session never mints one.

import { NextResponse } from "next/server";
import { OP_COOKIE } from "@/lib/operator-session";

export const dynamic = "force-dynamic";

export async function POST(): Promise<NextResponse> {
  const res = NextResponse.json({ ok: true });
  // Overwrite with an already-expired, empty cookie to evict it from the browser.
  res.cookies.set(OP_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return res;
}
