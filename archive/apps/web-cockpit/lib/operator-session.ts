// module: the operator session token — a compact, HMAC-signed, self-expiring cookie value proving the browser
// authenticated with the operator passphrase. Used by the login route (mint), the Edge middleware (verify at
// the gate), and the server proxy (re-verify before injecting the operator secret). Pure Web Crypto (globalThis
// .crypto.subtle) so it runs unchanged in the Edge runtime AND the Node runtime — zero npm deps.
//
// TOKEN FORMAT: `v1.<exp>.<sig>` where
//   • exp  = unix-seconds expiry (integer, base-10)
//   • sig  = base64url( HMAC-SHA256( key = OPERATOR_SESSION_SECRET, msg = `v1.<exp>` ) )
// The token carries no identity beyond "the operator" (single-user app) and no secret — only a MAC over the
// expiry. Verification recomputes the MAC in constant time and checks exp. Tampering with exp invalidates sig.
//
// SECURITY NOTES:
//   • constant-time compare (timingSafeEqualStr) — never a plain === on the signature.
//   • signing key is the raw OPERATOR_SESSION_SECRET (a long random string set on Vercel); if it is empty the
//     mint/verify both fail closed (no token can be produced or accepted).
//   • the cookie that carries this MUST be httpOnly + Secure + SameSite=Strict (set by the login route) so it
//     is never readable by JS and never sent cross-site.

export const OP_COOKIE = "cosmu_op";
const DEFAULT_TTL_SECONDS = 30 * 60; // ~30 min sessions — short, re-login is cheap.
const VERSION = "v1";

function b64urlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  // btoa is available in both Edge and Node (Node ≥16). Convert to base64url (no +/=).
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmacSha256(secret: string, msg: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return b64urlEncode(new Uint8Array(sig));
}

// Constant-time string compare (both operands are our own base64url MACs of fixed length; still compare without
// early-out to avoid leaking match length via timing).
function timingSafeEqualStr(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// mintOperatorToken — produce a signed token valid for ttlSeconds. Returns null when the secret is missing
// (fail closed — a keyless deploy can never mint a session, so enforcement can't be bypassed by a blank secret).
export async function mintOperatorToken(
  secret: string | undefined,
  ttlSeconds: number = DEFAULT_TTL_SECONDS,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<string | null> {
  if (!secret) return null;
  const exp = nowSeconds + ttlSeconds;
  const payload = `${VERSION}.${exp}`;
  const sig = await hmacSha256(secret, payload);
  return `${payload}.${sig}`;
}

// verifyOperatorToken — true iff the token is well-formed, its MAC matches (constant-time) under `secret`, and
// it has not expired. Any missing secret / malformed token / bad MAC / expiry → false (fail closed).
export async function verifyOperatorToken(
  token: string | undefined | null,
  secret: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<boolean> {
  if (!secret || !token) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [ver, expStr, sig] = parts;
  if (ver !== VERSION) return false;
  const exp = Number(expStr);
  if (!Number.isInteger(exp) || exp <= nowSeconds) return false;
  const expected = await hmacSha256(secret, `${ver}.${expStr}`);
  return timingSafeEqualStr(sig, expected);
}

export const OPERATOR_SESSION_TTL_SECONDS = DEFAULT_TTL_SECONDS;
