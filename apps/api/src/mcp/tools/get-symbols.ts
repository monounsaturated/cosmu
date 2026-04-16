import { listVenueSymbols } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const getSymbolsTool: ToolDefinition = {
  name: "get_symbols",
  description: "Fetch all tradable USDT spot symbols from Binance",
  execute: async () => {
    return listVenueSymbols();
  }
};
