// module: Agent-facing tool for resolving specific assets without prompt-wide pair lists.
import { resolveTradability } from "../../services/tradability.js";
import type { ToolDefinition } from "../types.js";

export const tradabilityResolveTool: ToolDefinition = {
  name: "tradability_resolve",
  description:
    "Resolve one specific asset or symbol against a venue. Use this instead of asking for a full pair list. Returns executable=false with a reason when the idea cannot trade on the selected venue.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      assetOrSymbol: { type: "string", description: "Asset or symbol to resolve, e.g. BTC, BTCUSDC, AAPL." },
      venue: { type: "string", description: "Venue id: binance, binance-testnet, ibkr-paper, or ibkr." },
      assetClass: { type: "string", description: "spot or equity." },
      sideIntent: { type: "string", description: "buy, sell, or watch." }
    },
    required: ["assetOrSymbol", "venue"],
    additionalProperties: false
  },
  execute: async (input) => resolveTradability(input)
};
