// module: the Trades feed fetcher — GET /executions. Every execution (paper + live) newest-first, each tagged
// `is_paper` with its owning strategy joined, for the single /trades page. Honest empty fallback (no fabricated
// fills); `connected:false` when the engine is unreachable so the page renders its not-connected state.

import type { ExecutionsResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyExecutions: ExecutionsResponse = { rows: [] };

export async function getExecutions(): Promise<{ data: ExecutionsResponse; connected: boolean }> {
  // Coalesce rows so a partial engine response can never .map-crash the table.
  const { data, connected } = await getJson<ExecutionsResponse>("/executions?limit=300", emptyExecutions);
  return { data: { rows: data.rows ?? [] }, connected };
}
