import { executeOrders } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const executeOrderTool: ToolDefinition = {
  name: "execute_order",
  description: "Execute one or more orders on Binance",
  execute: async (input) => {
    return executeOrders({
      runId: input.runId,
      runtimeConfig: input.runtimeConfig,
      orders: input.orders,
      venueContext: input.venueContext
    });
  }
};
