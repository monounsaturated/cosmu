import { loadVenueContext } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const getExchangeInfoTool: ToolDefinition = {
  name: "get_exchange_info",
  description: "Load full venue context (balances, prices, symbol rules) for a set of symbols",
  execute: async (input) => {
    return loadVenueContext(input.runtimeConfig, input.symbols);
  }
};
