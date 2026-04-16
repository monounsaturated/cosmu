import { getAccountBalance } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

export const getAccountTool: ToolDefinition = {
  name: "get_account",
  description: "Fetch current account balances from Binance",
  execute: async (_input, context) => {
    return getAccountBalance(context.mode);
  }
};
