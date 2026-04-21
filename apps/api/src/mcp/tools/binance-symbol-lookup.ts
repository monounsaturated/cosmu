import { lookupBinanceSymbols } from "../../adapters/binance.js";
import type { ToolDefinition } from "../types.js";

const MAX_SYMBOLS_PER_CALL = 10;

export const binanceSymbolLookupTool: ToolDefinition = {
  name: "binance_symbol_lookup",
  description:
    "Resolve up to 10 tickers on Binance spot. For each input, returns the best tradable pair quoted in a stablecoin (USDT preferred, USDC fallback). " +
    "You may pass a bare base ('NEIRO'), a USDT pair ('NEIROUSDT'), or a USDC pair ('NEIROUSDC') — in all cases the result's `symbol` field is the canonical pair you MUST use when placing an order. " +
    "Tradable shape: { tradable:true, symbol, quoteAsset, currentPrice, minQty, minNotional, tickSize, stepSize, orderTypes }. Non-tradable shape: { tradable:false, reason }. " +
    "Use this to (a) confirm a symbol is live before placing an order, and (b) get the authoritative current price for sizing stopLossPrice and takeProfitPrice.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      symbols: {
        type: "array",
        description:
          "Array of tickers — bare base like 'NEIRO', or a full pair like 'NEIROUSDT' / 'NEIROUSDC'. Max 10 per call. The response's `symbol` field is canonical.",
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
