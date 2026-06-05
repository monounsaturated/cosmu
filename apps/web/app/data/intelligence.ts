import { getJson } from "./client";

// GET /intelligence — system intelligence: "is the machine getting smarter?" Strategy funnel,
// gate efficiency trend, memory depth, regime coverage, data freshness, tick history, lineage.
export interface FunnelStats {
  authored: number;
  screened: number;
  gate_passed: number;
  funded: number;
  live: number;
  killed: number;
}

export interface GateEfficiency {
  current: number;
  trend: number[];
  improving: boolean;
}

export interface MemoryDepth {
  dead_ends: number;
  winners: number;
  skills: number;
  total: number;
}

export interface RegimeCell {
  regime: string;
  trend: string;
  vol: string;
  strategies: number;
}

export interface RegimeCoverage {
  grid: RegimeCell[];
  covered: number;
  total: number;
  by_label: Record<string, number>;
}

export interface DataSource {
  source: string;
  last_at: string | null;
  points: number;
}

export interface TickDetail {
  authored: number;
  passed: number;
  funded: number;
}

export interface TickStats {
  total: number;
  last_at: string | null;
  avg_survivors_per_tick: number;
  total_authored: number;
  total_survivors: number;
  recent: TickDetail[];
}

export interface LineageEntry {
  origin?: string;
  operator?: string;
  total: number;
  passed: number;
  rate: number;
}

export interface LineageStats {
  by_origin: LineageEntry[];
  by_operator: LineageEntry[];
}

export interface IntelligenceResponse {
  funnel: FunnelStats;
  gate_efficiency: GateEfficiency;
  memory: MemoryDepth;
  regime_coverage: RegimeCoverage;
  data_freshness: DataSource[];
  ticks: TickStats;
  lineage: LineageStats;
}

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
