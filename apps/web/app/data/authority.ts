// The AUTHORITY dashboard surface — proprietary data, not a strategy. Reads GET /authority: one composite row
// per account (Brier · hit-rate · EV/payoff · magnitude · lead-time · consistency · composite · top-3 movers),
// derived from whether the account's past asset calls corroborated the later tape (cosmu/authority/ computes it;
// cosmu/api/routers/authority.py serves it). READ-ONLY — the web only DISPLAYS the precomputed scoreboard; it
// never scores an account. Honest empty (n_accounts 0) until the local ingest + score pass has run on real
// account-call data — never a fabricated row.

import type { AuthorityResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyAuthority: AuthorityResponse = { as_of: null, n_accounts: 0, rows: [] };

export async function getAuthority(): Promise<{ authority: AuthorityResponse; connected: boolean }> {
  const { data, connected } = await getJson("/authority", emptyAuthority);
  // getJson swaps the typed default only on a FAILED fetch — coalesce `rows` (the table maps over it) the same
  // way the other data-layer readers do for a present-but-partial response.
  return { authority: { ...data, rows: data.rows ?? [] }, connected };
}
