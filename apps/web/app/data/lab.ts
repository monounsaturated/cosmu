import type { LabSymbolsResponse, TripletCardResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

// Structurally-empty fallback — never a fabricated row (honest not-connected / no-data state). min_trades is the
// gate trade floor the engine stamps so the table can flag `thin` cells; 0 here = "unknown" until the engine answers.
const emptyLabSymbols: LabSymbolsResponse = { rows: [], symbols: [], venues: [], timeframes: [], min_trades: 0 };

// Per-symbol backtest cells (strategy × symbol × venue), outlier-ranked by the engine (return desc). The SSR
// fetches the FIRST page (top-150 by return) for an instant, lightweight paint; the client table then
// background-pages through the rest via the engine proxy (?limit=&offset=) until `total_combos` is covered — so
// the operator can reach EVERY combo while the loaded set still filters/sorts/pages in-memory (snappy, no
// per-filter roundtrip). 150 keeps the SSR HTML small AND cuts the biggest single Supabase egress payload on the
// screener (a full 1,000-row hydrate on every page load) while still carrying the top combos + every funded Paper
// bot on top; the client immediately resumes paging from the SSR offset, so nothing below the fold is lost.
// Coalesce the arrays so a partial engine response can never white-screen the table.
export async function getLabSymbols(): Promise<{ data: LabSymbolsResponse; connected: boolean }> {
  const { data, connected } = await getJson<LabSymbolsResponse>("/lab/symbols?limit=150", emptyLabSymbols);
  return {
    // Preserve the engine's TRUE whole-set denominators (total_combos / total_strategies) — the prior coalesce
    // rebuilt `data` with only the arrays + min_trades and SILENTLY DROPPED both totals, so the page fell back to
    // the loaded-slice counts: the ribbon read "1,000 of 1,000" and the Strategies count showed the loaded
    // distinct algos, not the real 1,475. That drop is why the page and the sidebar (which reads total_strategies
    // straight off /leaderboard) disagreed. 0 = unknown (older engine) — the page then falls back honestly.
    data: {
      rows: data.rows ?? [],
      symbols: data.symbols ?? [],
      venues: data.venues ?? [],
      timeframes: data.timeframes ?? [],
      min_trades: data.min_trades ?? 0,
      total_combos: data.total_combos ?? 0,
      total_strategies: data.total_strategies ?? 0,
    },
    connected,
  };
}

// The 'fiche triplet' — the focused (algo × asset × venue) cell for a Version, given the clicked symbol/venue.
// `cell` is null when no backtest exists for that exact triplet (honest empty). Coalesce so a partial response
// never crashes the fiche.
export async function getTriplet(
  versionId: string,
  symbol?: string,
  venue?: string,
): Promise<{ data: TripletCardResponse; connected: boolean }> {
  const qs = new URLSearchParams();
  if (symbol) qs.set("symbol", symbol);
  if (venue !== undefined) qs.set("venue", venue); // "" addresses the NULL-venue sibling explicitly
  const q = qs.toString();
  const empty: TripletCardResponse = { strategy_id: "", strategy_version_id: versionId, strategy_name: "", cell: null };
  // Flat single-template URL (no nested backtick) so the static web↔engine route-reconcile guard can parse the
  // path; a trailing "?" when q is empty is harmless (FastAPI ignores an empty query string).
  const { data, connected } = await getJson<TripletCardResponse>(
    `/strategies/${versionId}/triplet?${q}`,
    empty,
  );
  return { data: { ...empty, ...data, cell: data.cell ?? null }, connected };
}

// The 'table de comparaison' — every cell of the SAME algo (across versions/assets/venues) for the side-by-side
// grid + the asset/venue selector. Same shape as the screener so it renders through SymbolsTable unchanged.
export async function getComparison(versionId: string): Promise<{ data: LabSymbolsResponse; connected: boolean }> {
  const { data, connected } = await getJson<LabSymbolsResponse>(`/strategies/${versionId}/comparison`, emptyLabSymbols);
  return {
    data: { rows: data.rows ?? [], symbols: data.symbols ?? [], venues: data.venues ?? [], timeframes: data.timeframes ?? [], min_trades: data.min_trades ?? 0 },
    connected,
  };
}
