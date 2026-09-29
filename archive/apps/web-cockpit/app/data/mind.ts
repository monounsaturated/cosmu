// The Mind's credibility surface — the followed-voices scoreboard (realtime-data-lane P2). Reads
// GET /mind/credibility: one flat row per pre-registered voice with its Brier-skill + citation-authority
// (cosmu/ingest/voices_pass.py writes it; cosmu/api/routers/mind.py serves it). READ-ONLY — the web only
// DISPLAYS the scoreboard the engine computes; it never scores a voice. Honest empty (panel_size 0) until
// voices are registered in config/voices.py and the credibility pass has run — never a fabricated row.

import type { CredibilityResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyCredibility: CredibilityResponse = { as_of: null, panel_size: 0, rows: [] };

export async function getCredibility(): Promise<{ credibility: CredibilityResponse; connected: boolean }> {
  const { data, connected } = await getJson("/mind/credibility", emptyCredibility);
  // getJson swaps the typed default only on a FAILED fetch — a present-but-partial response passes through
  // raw, so coalesce `rows` (the table maps over it) the same way the other data-layer readers do.
  return { credibility: { ...data, rows: data.rows ?? [] }, connected };
}
