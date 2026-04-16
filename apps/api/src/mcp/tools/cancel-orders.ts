import { cancelAllOpenOrdersForSymbol } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const cancelOrdersTool: ToolDefinition = {
  name: "cancel_orders",
  description: "Cancel all open orders for a given symbol on Binance",
  execute: async (input, context) => {
    return cancelAllOpenOrdersForSymbol(context.mode, input.symbol);
  }
};
