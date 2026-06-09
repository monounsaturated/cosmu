import type { DataSource, FunnelStats, IntelligenceResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

// GET /intelligence — system intelligence: "is the machine getting smarter?" Strategy funnel,
// gate efficiency trend, memory depth, regime coverage, data freshness, tick history, lineage.
// All shapes come from the generated @cosmu/contracts-ts — never hand-typed.

// Re-exported so consumers keep importing these from "@/app/data" like every other surface type.
export type { DataSource, FunnelStats, IntelligenceResponse };

const emptyIntelligence: IntelligenceResponse = {
  funnel: { authored: 0, screened: 0, gate_passed: 0, funded: 0, live: 0, killed: 0 },
  gate_efficiency: { current: 0, trend: [], improving: false },
  memory: { dead_ends: 0, winners: 0, skills: 0, total: 0 },
  regime_coverage: { grid: [], covered: 0, total: 9, by_label: {} },
  data_freshness: [],
  ticks: { total: 0, last_at: null, avg_survivors_per_tick: 0, total_authored: 0, total_survivors: 0, recent: [] },
  lineage: { by_origin: [], by_operator: [] },
};

export async function getIntelligence(): Promise<{ intelligence: IntelligenceResponse; connected: boolean }> {
  const { data, connected } = await getJson("/intelligence", emptyIntelligence);
  return { intelligence: data, connected };
}
