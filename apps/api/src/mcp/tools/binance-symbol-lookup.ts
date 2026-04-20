import { lookupBinanceSymbols } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

const MAX_SYMBOLS_PER_CALL = 10;

export const binanceSymbolLookupTool: ToolDefinition = {
  name: "binance_symbol_lookup",
  description:
    "Check up to 10 specific Binance USDT spot pairs at once. Returns per-symbol { tradable, currentPrice, minQty, minNotional, tickSize, stepSize, orderTypes } or { tradable:false, reason } if the pair does not exist / is halted. " +
    "Pass ONLY the exact tickers you are considering trading (e.g. ['BTCUSDT','WIFUSDT']). Do NOT request bulk lists. " +
    "Use this to (a) confirm a symbol is live before placing an order, and (b) get the authoritative current price for sizing stopLossPrice and takeProfitPrice.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      symbols: {
        type: "array",
        description:
          "Array of full Binance USDT pair tickers (uppercase, e.g. 'BTCUSDT'). Max 10 per call.",
        items: { type: "string" }
      }
    },
    required: ["symbols"],
    additionalProperties: false
  },
  execute: async (input, context) => {
    const raw = Array.isArray(input?.symbols) ? (input.symbols as unknown[]) : [];
    const symbols = raw
      .slice(0, MAX_SYMBOLS_PER_CALL)
      .map((s) => String(s ?? "").trim().toUpperCase());

    if (symbols.length === 0) {
      return {
        error:
          "No symbols provided. Pass symbols as an array of ticker strings, e.g. { \"symbols\": [\"BTCUSDT\"] }."
      };
    }

    return lookupBinanceSymbols(context.mode, symbols);
  }
};
