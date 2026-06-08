// module: the CORRELATIONS data adapter. Feeds the /correlations surface from the engine's
// `correlation_findings` ledger via GET /correlations (server-side engine proxy). This is the
// machine's TRACKED correlation memory: one finding per (run × feature × source × asset × horizon)
// carrying the point-in-time INFORMATION COEFFICIENT (IC), its n / p / BH-FDR survival, and an
// HONEST non-causal note read from the feature_registry prior.
//
// HONESTY MODEL (inherited from ./client): every fetch returns `{ data, connected }`.
//   - connected === false -> the engine is unreachable. The UI renders "Engine not connected",
//                            never numbers.
//   - connected === true  -> real engine data. It may still be structurally EMPTY (no findings yet);
//                            the UI renders the honest "no findings yet — run the sweep" state.
// PROPOSE-ONLY: a surviving IC is a *candidate hypothesis*, NEVER an edge. The deterministic Gate is
// the disposal layer — "scan proposes, Gate disposes". Nothing here gates or moves money.
//
// CONTRACT MIRROR: these field names mirror the engine ledger columns
//   run_id · ts · feature · source · asset · horizon · ic · n · p · fdr_survived · deflated_note · data_source
// 1:1, so when the engine stream's GET /correlations contract is regenerated into @cosmu/contracts-ts
// the orchestrator can reconcile this local shape against it. Types are defined LOCALLY here (not
// imported from the contracts package) so this surface compiles before the contract is generated.

import { getJson } from "./client";

// ── One finding: a single (run × feature × source × asset × horizon) IC row ──────────────────────
// Mirrors the `correlation_findings` ledger row exactly (cosmu/master/correlation_ledger.py).
export interface CorrelationFinding {
  /** Ties every row of one scan run together — the unit of decay-tracking. */
  run_id: string;
  /** ISO timestamp the finding was recorded (run time). */
  ts: string;
  /** The feature_registry feature name (e.g. "funding_rate_8h"). */
  feature: string;
  /** The alt-data source the feature came from. */
  source: string;
  /** The asset the IC was measured against (or "MARKET" for market-wide series). */
  asset: string;
  /** Forward-return horizon in bars. */
  horizon: number;
  /** Point-in-time Spearman IC: feature known at t vs the strictly-future return t→t+h. */
  ic: number;
  /** Observation count behind the IC. */
  n: number;
  /** Two-sided p-value for the IC. */
  p: number;
  /** Whether the IC survived the run's BH-FDR pass (q=0.10) — a *candidate*, never an edge. */
  fdr_survived: boolean;
  /** Honest causal-trust note from the feature_registry prior; empty for a plain feature.
   *  Non-empty + non-causal => "NON-CAUSAL CONTROL …"; the Gate disposes. */
  deflated_note: string;
  /** "live" or a fixture tag — a test scan never pollutes the live correlation memory. */
  data_source: string;
}

// ── A tracked correlation's IC history across runs (decay series) ────────────────────────────────
// One series per (feature × asset × horizon), OLDEST first, so a sparkline shows how the IC moves
// run-over-run — a strong IC that fades is the tell a single scan can't show.
export interface TrackedCorrelation {
  feature: string;
  source: string;
  asset: string;
  horizon: number;
  /** The non-causal / low-confidence note carried by the latest point in the series. */
  deflated_note: string;
  /** IC per run, oldest → newest. Length ≥ 1; the sparkline needs ≥ 2 to draw. */
  history: number[];
  /** ISO timestamps aligned to `history` (oldest → newest). */
  timestamps: string[];
  /** The most-recent IC in the series — the "now" of the correlation. */
  latest_ic: number;
  /** Whether the latest point survived BH-FDR. */
  latest_fdr_survived: boolean;
}

export interface CorrelationsResponse {
  /** The most-recent scan run id, if any — the snapshot the heatmap + table show. */
  run_id: string | null;
  /** When the latest scan ran (ISO), if any. */
  generated_at: string | null;
  /** Flat list of the latest findings, newest first (one row per finding). */
  findings: CorrelationFinding[];
  /** Per-(feature × asset × horizon) IC history for the decay sparklines. */
  tracked: TrackedCorrelation[];
}

// Structurally-empty fallback — ZERO fabricated numbers, ZERO fake rows. Lets the types resolve and
// the page render its honest empty / not-connected state.
const emptyCorrelations: CorrelationsResponse = {
  run_id: null,
  generated_at: null,
  findings: [],
  tracked: []
};

// Coerce one raw finding into the typed shape, tolerating the engine's int-boolean for fdr_survived
// (the ledger stores 1/0) and missing optional fields. Never fabricates: a bad row degrades to a
// safe, plainly-empty finding rather than inventing a correlation.
function normalizeFinding(raw: Partial<CorrelationFinding> & { fdr_survived?: boolean | number }): CorrelationFinding {
  return {
    run_id: String(raw.run_id ?? ""),
    ts: String(raw.ts ?? ""),
    feature: String(raw.feature ?? ""),
    source: String(raw.source ?? ""),
    asset: String(raw.asset ?? ""),
    horizon: Number(raw.horizon ?? 0),
    ic: Number(raw.ic ?? 0),
    n: Number(raw.n ?? 0),
    p: Number(raw.p ?? 1),
    fdr_survived: Boolean(raw.fdr_survived),
    deflated_note: String(raw.deflated_note ?? ""),
    data_source: String(raw.data_source ?? "")
  };
}

function normalizeTracked(
  raw: Partial<TrackedCorrelation> & { latest_fdr_survived?: boolean | number }
): TrackedCorrelation {
  const history = Array.isArray(raw.history) ? raw.history.map(Number) : [];
  const timestamps = Array.isArray(raw.timestamps) ? raw.timestamps.map(String) : [];
  return {
    feature: String(raw.feature ?? ""),
    source: String(raw.source ?? ""),
    asset: String(raw.asset ?? ""),
    horizon: Number(raw.horizon ?? 0),
    deflated_note: String(raw.deflated_note ?? ""),
    history,
    timestamps,
    latest_ic: Number(raw.latest_ic ?? (history.length > 0 ? history[history.length - 1] : 0)),
    latest_fdr_survived: Boolean(raw.latest_fdr_survived)
  };
}

export async function getCorrelations(): Promise<{ correlations: CorrelationsResponse; connected: boolean }> {
  const { data, connected } = await getJson<CorrelationsResponse>("/correlations", emptyCorrelations);
  return {
    correlations: {
      run_id: data.run_id ?? null,
      generated_at: data.generated_at ?? null,
      findings: (data.findings ?? []).map(normalizeFinding),
      tracked: (data.tracked ?? []).map(normalizeTracked)
    },
    connected
  };
}
