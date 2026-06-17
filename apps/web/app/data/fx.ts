// EUR → USD daily rate. Server-side only.
//
// Pulls the current ECB reference rate from Frankfurter (free, no API key) and caches it for ~24h via the
// Next data cache, so the Costs page re-rates EUR spend once a day instead of freezing on a constant. Any
// failure (offline, API down, bad shape) falls back to FALLBACK_EUR_USD — the page never breaks on FX.

import { FALLBACK_EUR_USD } from "./cost-register";

export async function getEurUsd(): Promise<number> {
  try {
    const res = await fetch("https://api.frankfurter.app/latest?from=EUR&to=USD", {
      next: { revalidate: 86400 }, // refresh at most once a day
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return FALLBACK_EUR_USD;
    const body = (await res.json()) as { rates?: { USD?: number } };
    const rate = body?.rates?.USD;
    return typeof rate === "number" && rate > 0 ? rate : FALLBACK_EUR_USD;
  } catch {
    return FALLBACK_EUR_USD;
  }
}
