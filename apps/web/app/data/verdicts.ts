import { getJson } from "./client";

// ── Verdict ledger ──────────────────────────────────────────────────────────

export interface VerdictRow {
  slug: string;
  thesis: string;
  id: string;
  date: string;
  status: "PASS" | "FAIL" | "INSUFFICIENT-DATA" | "DATA-BLOCKED";
  deflated_sharpe: number | null;
  trades: number | null;
  cost_ratio: number | null;
  reason: string;
}

export interface VerdictsResponse {
  rows: VerdictRow[];
}

export type VerdictItem = VerdictRow;

const emptyVerdicts: VerdictsResponse = { rows: [] };

export async function getVerdicts(): Promise<{ verdicts: VerdictsResponse; connected: boolean }> {
  const { data, connected } = await getJson<VerdictsResponse>("/verdicts", emptyVerdicts);
  return { verdicts: { rows: data.rows ?? [] }, connected };
}
