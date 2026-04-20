import type { ToolDefinition, ToolContext, ToolCallResult } from "./types.js";
import { getAccountTool } from "./tools/get-account.js";
import { getPricesTool } from "./tools/get-prices.js";
import { getSymbolsTool } from "./tools/get-symbols.js";
import { getExchangeInfoTool } from "./tools/get-exchange-info.js";
import { executeOrderTool } from "./tools/execute-order.js";
import { cancelOrdersTool } from "./tools/cancel-orders.js";
import { binanceSymbolLookupTool } from "./tools/binance-symbol-lookup.js";

export type { ToolContext, ToolCallResult };

const toolRegistry = new Map<string, ToolDefinition>();

const register = (tool: ToolDefinition) => {
  toolRegistry.set(tool.name, tool);
};

// Register all built-in tools
register(getAccountTool);
register(getPricesTool);
register(getSymbolsTool);
register(getExchangeInfoTool);
register(executeOrderTool);
register(cancelOrdersTool);
register(binanceSymbolLookupTool);

/** Call a registered tool by name. */
export const callTool = async <T = unknown>(
  name: string,
  input: unknown,
  context: ToolContext
): Promise<ToolCallResult<T>> => {
  const tool = toolRegistry.get(name);
  if (!tool) {
    return {
      toolName: name,
      input,
      output: null as T,
      latencyMs: 0,
      error: `Tool "${name}" not found`
    };
  }

  const start = Date.now();
  try {
    const output = await tool.execute(input, context);
    return {
      toolName: name,
      input,
      output: output as T,
      latencyMs: Date.now() - start,
      error: null
    };
  } catch (error) {
    return {
      toolName: name,
      input,
      output: null as T,
      latencyMs: Date.now() - start,
      error: error instanceof Error ? error.message : String(error)
    };
  }
};

/** List all registered tools (for introspection / future agent use). */
export const listTools = () =>
  Array.from(toolRegistry.values()).map((tool) => ({
    name: tool.name,
    description: tool.description
  }));

/** Return the set of tools that can be invoked by an LLM agent. */
export const getAgentFacingTools = (): ToolDefinition[] =>
  Array.from(toolRegistry.values()).filter(
    (tool) => tool.agentFacing === true && tool.inputSchema !== undefined
  );

export { toolRegistry };
