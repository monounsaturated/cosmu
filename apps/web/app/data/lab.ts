import type { LabSymbolsResponse } from "@cosmu/contracts-ts";
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
