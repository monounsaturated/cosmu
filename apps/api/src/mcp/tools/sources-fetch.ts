// module: Agent-facing source fetch tool; stores raw observations with provenance.
import { fetchSourceToObservations } from "../../sources/registry.js";
import type { ToolDefinition } from "../types.js";

export const sourcesFetchTool: ToolDefinition = {
  name: "sources_fetch",
  description:
    "Fetch a registered read-only data source and store the result as raw observations. Use for specific queries only; do not bulk crawl.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      sourceKey: { type: "string", description: "Registered source key, e.g. yahoo_finance." },
      query: { type: "string", description: "Specific symbol/topic/query." },
      limit: { type: "number", description: "Maximum observations to fetch." }
    },
    required: ["sourceKey", "query"],
    additionalProperties: false
  },
  execute: async (input) => {
    const sourceKey = String(input?.sourceKey ?? "");
    return fetchSourceToObservations(sourceKey, {
      query: String(input?.query ?? ""),
      limit: Number(input?.limit ?? 5)
    });
  }
};
