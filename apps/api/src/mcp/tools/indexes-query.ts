// module: Agent-facing index query tool for latest configured indexes.
import { listIndexConfigs, listIndexSnapshots } from "../../lib/store.js";
import type { ToolDefinition } from "../types.js";

export const indexesQueryTool: ToolDefinition = {
  name: "indexes_query",
  description: "List indexes or recent snapshots for a specific index id.",
  agentFacing: true,
  inputSchema: {
    type: "object",
    properties: {
      indexId: { type: "string", description: "Optional index UUID. Omit to list index configs." },
      limit: { type: "number", description: "Maximum snapshots when indexId is provided." }
    },
    additionalProperties: false
  },
  execute: async (input) => {
    if (typeof input?.indexId === "string" && input.indexId.trim()) {
      return { snapshots: await listIndexSnapshots(input.indexId.trim(), Number(input?.limit ?? 10)) };
    }
    return { indexes: await listIndexConfigs() };
  }
};
