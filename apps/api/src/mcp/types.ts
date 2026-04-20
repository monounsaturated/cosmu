import type { RuntimeConfig } from "@cosmu/shared";

/** Context passed to every MCP tool execution. */
export type ToolContext = {
  mode: RuntimeConfig["mode"];
};

/** JSON Schema-like description of a tool's parameters (agent-callable tools only). */
export type ToolInputSchema = {
  type: "object";
  properties: Record<string, unknown>;
  required?: string[];
  additionalProperties?: boolean;
};

/** Definition of a single MCP tool. */
export type ToolDefinition = {
  name: string;
  description: string;
  /** When set, this tool is exposed to LLM agents (research/trader). */
  inputSchema?: ToolInputSchema;
  /** Set to true to expose this tool to LLM agents. Requires inputSchema. */
  agentFacing?: boolean;
  execute: (input: any, context: ToolContext) => Promise<unknown>;
};

/** Result of calling a tool through the registry. */
export type ToolCallResult<T = unknown> = {
  toolName: string;
  input: unknown;
  output: T;
  latencyMs: number;
  error: string | null;
};
