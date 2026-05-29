// module: Agent-facing signal query tool for research/trader context.
import { listStandardizedSignals } from "../../lib/store.js";
import type { ToolDefinition } from "../types.js";

export const signalsQueryTool: ToolDefinition = {
  name: "signals_query",
  description: "Query recent standardized signals by asset/status. Use this before relying on stored qualitative data.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      asset: { type: "string", description: "Optional asset/ticker filter." },
      status: { type: "string", description: "Optional status: new, watching, used, dismissed." },
      limit: { type: "number", description: "Maximum signals to return." }
    },
    additionalProperties: false
  },
  execute: async (input) => listStandardizedSignals({
    asset: typeof input?.asset === "string" && input.asset.trim() ? input.asset.trim() : undefined,
    status: ["new", "watching", "used", "dismissed"].includes(String(input?.status))
      ? input.status
      : undefined,
    limit: Number(input?.limit ?? 10)
  })
};
