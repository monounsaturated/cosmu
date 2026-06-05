import type { CostsResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

const emptyCosts: CostsResponse = {
  total_usd: 0,
  by_category: [],
  opex_vs_alpha: 0,
  per_strategy: [],
  infra_lines: [],
  llm_calls: { call_count: 0, total_cost: 0, by_task: {} },
  vendor_actuals: [],
};

// GET /costs — the dedicated ROI view (opex vs alpha, spend by category, per-strategy attribution).
export async function getCosts(): Promise<{ costs: CostsResponse; connected: boolean }> {
  const { data, connected } = await getJson("/costs", emptyCosts);
  // Normalize: a deployed engine on an older shape may omit the newer arrays (e.g. vendor_actuals),
  // which would crash prerender on `.length`. Coerce every array/object field to a safe default.
  const costs: CostsResponse = {
    ...emptyCosts,
    ...data,
    by_category: data.by_category ?? [],
    per_strategy: data.per_strategy ?? [],
    infra_lines: data.infra_lines ?? [],
    vendor_actuals: data.vendor_actuals ?? [],
    llm_calls: data.llm_calls ?? emptyCosts.llm_calls,
  };
  return { costs, connected };
}
