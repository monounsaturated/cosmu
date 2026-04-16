import { getAllTickerPrices } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const getPricesTool: ToolDefinition = {
  name: "get_prices",
  description: "Fetch current ticker prices from Binance. Optionally filter to specific symbols.",
  execute: async (input, context) => {
    const allPrices = await getAllTickerPrices(context.mode);
    const priceMap: Record<string, number> = {};
    const symbols: string[] | undefined = input?.symbols;
    const symbolFilter = symbols ? new Set(symbols.map((s: string) => s.toUpperCase())) : null;

    for (const entry of (Array.isArray(allPrices) ? allPrices : [])) {
      const symbol = String(entry.symbol ?? "").toUpperCase();
      if (symbolFilter && !symbolFilter.has(symbol)) continue;
      priceMap[symbol] = Number(entry.price);
    }

    return priceMap;
  }
};
