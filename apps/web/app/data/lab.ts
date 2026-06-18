import type { LabSymbolsResponse, TripletCardResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

// Structurally-empty fallback — never a fabricated row (honest not-connected / no-data state).
const emptyLabSymbols: LabSymbolsResponse = { rows: [], symbols: [], venues: [] };

// Per-symbol backtest cells (strategy × symbol × venue), outlier-ranked + verdict-labelled by the engine. We
// fetch the whole set (capped) once on the server and let the table filter/sort in-memory — snappy, no
// per-filter roundtrip. Coalesce the arrays so a partial engine response can never white-screen the table.
export async function getLabSymbols(): Promise<{ data: LabSymbolsResponse; connected: boolean }> {
  const { data, connected } = await getJson<LabSymbolsResponse>("/lab/symbols?limit=1000", emptyLabSymbols);
  return {
    data: { rows: data.rows ?? [], symbols: data.symbols ?? [], venues: data.venues ?? [] },
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
    data: { rows: data.rows ?? [], symbols: data.symbols ?? [], venues: data.venues ?? [] },
    connected,
  };
}
