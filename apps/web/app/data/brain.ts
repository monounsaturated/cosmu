import type { BrainResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyBrain: BrainResponse = {
  llm: "off",
  gated: { generated: 0, passed: 0, killed: 0, kill_rate: 0 },
  survivors: [],
  graveyard: [],
  sources: [],
  tools: [],
  regime: { label: "unknown", vol_bucket: "—", trend: "flat" },
  survival_ranking: []
};

// GET /research/brain — the research brain: LLM on/off, the deterministic gate funnel, survivors,
// graveyard, regime, data sources, bus tools, and the survival-model ranking. The ranking only
// ORDERS the validation queue (which candidate to compute first) — it never vetoes.
export async function getBrain(): Promise<{ brain: BrainResponse; connected: boolean }> {
  const { data, connected } = await getJson("/research/brain", emptyBrain);
  return { brain: data, connected };
}
