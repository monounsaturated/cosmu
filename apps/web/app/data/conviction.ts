// The Conviction review queue — propose-only conviction trade proposals built from high-authority accounts'
// fresh asset-calls (cosmu/conviction). Reads GET /conviction/proposals: each row carries the asset + direction,
// the capped size + hard max-loss + expiry, the plain-language thesis, and the authority evidence the human
// reviews before arming. READ-ONLY — the web only DISPLAYS the queue; the engine produces it (out-of-band in the
// voices pass) and NOTHING here arms or moves money. Honest-empty (count 0) until the producer fills it.

import type { ConvictionProposalsResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyConviction: ConvictionProposalsResponse = { count: 0, armed: false, proposals: [] };

export async function getConvictionProposals(): Promise<{
  conviction: ConvictionProposalsResponse;
  connected: boolean;
}> {
  const { data, connected } = await getJson("/conviction/proposals", emptyConviction);
  // getJson swaps the typed default only on a FAILED fetch — coalesce `proposals` the same way the other
  // data-layer readers coalesce their list field, in case of a present-but-partial response.
  return { conviction: { ...data, proposals: data.proposals ?? [] }, connected };
}
