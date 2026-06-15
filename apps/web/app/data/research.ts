// module: research data adapter — the machine's EXPERIMENT MEMORY (/research/experiments). Every theory the
// machine has tested through the honest cohort Gate (gate_verdicts, kind='cohort', BH-FDR corrected): the
// plain-language hypothesis, its source, the PASS/STOP verdict, the best in-sample deflated-Sharpe prob vs the
// 0.95 bar, and the REAL out-of-sample holdout dSR (so overfit is legible). The engine endpoint returns an
// untyped dict (no response_model), so the shape is declared HERE, next to its only consumer. The fallback is
// structurally empty — an honest "nothing tested yet", never a fabricated row.

import { getJson } from "./client";

export type ExperimentCandidate = {
  id: string | null;
  label: string | null;
  promoted: boolean;
  deflated_sharpe_prob: number | null;
  holdout_deflated_sharpe: number | null;
  survived_fdr: boolean | null;
  reasons: string[];
};

export type ExperimentTheory = {
  run_id: string | null;
  ts: string;
  source: string;
  hypothesis: string;
  decision: string;
  kind: string | null;
  method: string;
  asset: string | null;
  n_candidates: number;
  n_promoted: number;
  best_dsr: number;
  best_holdout_dsr: number | null;
  candidates: ExperimentCandidate[];
};

export type ExperimentsSummary = {
  total: number;
  passed: number;
  failed: number;
  by_source: { source: string; n: number; passed: number }[];
};

export type ExperimentsResponse = {
  summary: ExperimentsSummary;
  theories: ExperimentTheory[];
};

const emptyExperiments: ExperimentsResponse = {
  summary: { total: 0, passed: 0, failed: 0, by_source: [] },
  theories: [],
};

export async function getExperiments(): Promise<{ experiments: ExperimentsResponse; connected: boolean }> {
  const { data, connected } = await getJson<ExperimentsResponse>("/research/experiments", emptyExperiments);
  return { experiments: data, connected };
}
