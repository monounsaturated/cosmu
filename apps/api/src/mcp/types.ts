import type { RuntimeConfig } from "@cosmu/shared";

/** Context passed to every MCP tool execution. */
export type ToolContext = {
  mode: RuntimeConfig["mode"];
};

/** Definition of a single MCP tool. */
export type ToolDefinition = {
  name: string;
  description: string;
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
