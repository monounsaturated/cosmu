// module: operator LOGIN — exchange the operator passphrase for a short-lived, HMAC-signed `cosmu_op` session
// cookie that unlocks the money control plane (once OPERATOR_AUTH_ENFORCED is on). Single-user app: there is one
// passphrase; a POST with the correct passphrase mints the cookie, anything else is a flat 401. This route is
// harmless while the dark-launch flag is off (nothing consumes the cookie yet) and becomes meaningful the moment
// enforcement is flipped on.
//
// SECRETS (Vercel server env — never NEXT_PUBLIC):
//   • OPERATOR_PASSPHRASE_HASH  — sha256 hex of the operator passphrase (compute once: it never stores the
//     plaintext). Use a LONG, RANDOM passphrase — the hash is a fast digest, so its security rests on the
//     passphrase's entropy, not on a slow KDF.
//   • OPERATOR_SESSION_SECRET   — the HMAC key the token is signed with (a long random string).
// Both must be set for login to succeed; a missing secret fails closed (500 / no mint).

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { mintOperatorToken, OP_COOKIE, OPERATOR_SESSION_TTL_SECONDS } from "@/lib/operator-session";

export const dynamic = "force-dynamic";

// sha256 hex of a string via Web Crypto (Edge + Node). Lowercase hex to match a canonical stored hash.
async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Constant-time hex-string compare (both are fixed-length sha256 hex digests). No early-out on mismatch.
function timingSafeEqualStr(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const expectedHash = process.env.OPERATOR_PASSPHRASE_HASH;
  const sessionSecret = process.env.OPERATOR_SESSION_SECRET;
  if (!expectedHash || !sessionSecret) {
    // Fail closed: without both secrets configured, login cannot mint a valid session.
    return NextResponse.json({ detail: "operator auth not configured" }, { status: 500 });
  }

  let passphrase = "";
  try {
    const body = (await req.json()) as { passphrase?: unknown };
    passphrase = typeof body?.passphrase === "string" ? body.passphrase : "";
  } catch {
    passphrase = "";
  }
  if (!passphrase) {
    return NextResponse.json({ detail: "passphrase required" }, { status: 401 });
  }

  const presentedHash = await sha256Hex(passphrase);
  if (!timingSafeEqualStr(presentedHash, expectedHash.trim().toLowerCase())) {
    return NextResponse.json({ detail: "invalid passphrase" }, { status: 401 });
  }

  const token = await mintOperatorToken(sessionSecret);
  if (!token) {
    return NextResponse.json({ detail: "operator auth not configured" }, { status: 500 });
  }

  const res = NextResponse.json({ ok: true, expiresInSeconds: OPERATOR_SESSION_TTL_SECONDS });
  res.cookies.set(OP_COOKIE, token, {
    httpOnly: true, // never readable by JS — not exfiltratable via XSS
    secure: true, // HTTPS only
    sameSite: "strict", // never sent cross-site — CSRF-hardened
    path: "/",
    maxAge: OPERATOR_SESSION_TTL_SECONDS,
  });
  return res;
}
