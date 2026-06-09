// module: the CORRELATIONS data adapter. Feeds the /correlations surface from the engine's
// `correlation_findings` ledger via GET /correlations (server-side engine proxy). This is the
// machine's TRACKED correlation memory: one finding per (run × feature × source × asset × horizon)
// carrying the point-in-time INFORMATION COEFFICIENT (IC), its n / p / BH-FDR survival, an HONEST
// non-causal flag, plus the latest run's heatmap and per-feature stability (decay) series.
//
// HONESTY MODEL (inherited from ./client): every fetch returns `{ data, connected }`.
//   - connected === false -> the engine is unreachable. The UI renders "Engine not connected",
//                            never numbers.
//   - connected === true  -> real engine data. It may still be structurally EMPTY (no findings yet);
//                            the UI renders the honest "no findings yet — run the sweep" state.
// PROPOSE-ONLY: a surviving IC is a *candidate hypothesis*, NEVER an edge. The deterministic Gate is
// the disposal layer — "scan proposes, Gate disposes". Nothing here gates or moves money.
//
// CONTRACT: all shapes come from the generated @cosmu/contracts-ts (Pydantic -> OpenAPI -> TS;
// never hand-typed) — the single source of truth for GET /correlations. No local mirror to drift.

import type {
  CorrelationFinding,
  CorrelationHeatmap,
  CorrelationStability,
  CorrelationsResponse,
} from "@cosmu/contracts-ts";
import { getJson } from "./client";

// Re-exported so the surface keeps importing its types from "@/app/data" like every other page.
export type { CorrelationFinding, CorrelationHeatmap, CorrelationStability, CorrelationsResponse };

// Structurally-empty fallback — ZERO fabricated numbers, ZERO fake rows. Lets the types resolve and
// the page render its honest empty / not-connected state.
const emptyHeatmap: CorrelationHeatmap = { horizon: null, features: [], assets: [], cells: [] };

const emptyCorrelations: CorrelationsResponse = {
  latest_run_id: null,
  latest: [],
  survivors: [],
  heatmap: emptyHeatmap,
  stability: []
};

export async function getCorrelations(): Promise<{ correlations: CorrelationsResponse; connected: boolean }> {
  const { data, connected } = await getJson<CorrelationsResponse>("/correlations", emptyCorrelations);
  // Coerce arrays/objects so an older deployed engine omitting a newer field can never crash render.
  return {
    correlations: {
      latest_run_id: data.latest_run_id ?? null,
      latest: data.latest ?? [],
      survivors: data.survivors ?? [],
      heatmap: data.heatmap ?? emptyHeatmap,
      stability: data.stability ?? []
    },
    connected
  };
}
