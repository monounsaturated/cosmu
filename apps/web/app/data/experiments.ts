import { getJson } from "./client";

// ── Experiment memory ────────────────────────────────────────────────────────
// The machine's durable memory: every trading theory it has ever tested, with the
// honest Gate's verdict (PASS/FAIL). Backed by the live `gate_verdicts` DB table via
// the engine's `GET /research/experiments` endpoint — NOT stale markdown.
//
// Honesty model: identical to every other data module. `connected:false` → the engine
// is unreachable and the UI renders an honest "not connected" state, never numbers.
// The fallback below is structurally EMPTY (zero rows, zero fabricated counts).

// One candidate inside a theory's cohort — the actual spec the Gate ruled on.
export interface ExperimentCandidate {
  id: string;
  label: string | null;
  promoted: boolean;
  /** In-sample deflated Sharpe probability (0..1). The Gate's 0.95 bar. */
  deflated_sharpe_prob: number;
  /** Out-of-sample (holdout) deflated Sharpe. null when no holdout was run. */
  holdout_deflated_sharpe: number | null;
  /** Survived the cohort's BH-FDR multiple-testing correction. */
  survived_fdr: boolean;
  /** Kill reasons (empty when promoted). */
  reasons: string[];
}

// One theory = one pre-registered hypothesis tested as a cohort, with its verdict.
export interface ExperimentTheory {
  run_id: string;
  ts: string; // ISO timestamp
  source: string; // e.g. "youtube", "x", "scan", "pine", "manual"
  hypothesis: string; // plain-language statement of the theory
  decision: "PASS" | "FAIL";
  kind: string; // e.g. "single-signal", "cross-asset"
  asset: string | null;
  n_candidates: number;
  n_promoted: number;
  /** Best in-sample deflated-Sharpe probability across the cohort (0..1). */
  best_dsr: number;
  /** Best holdout deflated Sharpe; null when no holdout. Negative => decays OOS. */
  best_holdout_dsr: number | null;
  candidates: ExperimentCandidate[];
}

export interface ExperimentsSummaryBySource {
  source: string;
  n: number;
  passed: number;
}

export interface ExperimentsSummary {
  total: number;
  passed: number;
  failed: number;
  by_source: ExperimentsSummaryBySource[];
}

export interface ExperimentsResponse {
  summary: ExperimentsSummary;
  theories: ExperimentTheory[];
}

const emptyExperiments: ExperimentsResponse = {
  summary: { total: 0, passed: 0, failed: 0, by_source: [] },
  theories: []
};

export async function getExperiments(): Promise<{
  experiments: ExperimentsResponse;
  connected: boolean;
}> {
  const { data, connected } = await getJson<ExperimentsResponse>(
    "/research/experiments",
    emptyExperiments
  );
  // Normalise so the UI can rely on arrays/fields existing even if the engine omits them.
  const summary = data.summary ?? emptyExperiments.summary;
  return {
    experiments: {
      summary: {
        total: summary.total ?? 0,
        passed: summary.passed ?? 0,
        failed: summary.failed ?? 0,
        by_source: summary.by_source ?? []
      },
      theories: (data.theories ?? []).map((t) => ({
        ...t,
        candidates: t.candidates ?? []
      }))
    },
    connected
  };
}
