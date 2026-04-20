/**
 * Tool Definition Adapters (provider-agnostic → vendor wire format)
 *
 * Our internal tool registry (`src/mcp/types.ts`) stores tools in an MCP-compatible
 * shape:
 *   { name, description, inputSchema: { type: "object", properties, required } }
 *
 * Each LLM vendor expects a slightly different wire format when exposing these
 * tools to a chat/completions call. Transform at the boundary — do NOT leak
 * vendor shapes into the registry.
 *
 *   ┌─────────────────┬────────────────────────────────────────────────────────┐
 *   │ Vendor          │ Request-side shape                                     │
 *   ├─────────────────┼────────────────────────────────────────────────────────┤
 *   │ OpenAI / xAI /  │ { type: "function",                                    │
 *   │ any OpenAI-     │   function: { name, description, parameters } }        │
 *   │ compatible API  │ assistant reply: { tool_calls: [{ id, function }] }    │
 *   │                 │ tool result:   { role: "tool", tool_call_id, content } │
 *   ├─────────────────┼────────────────────────────────────────────────────────┤
 *   │ Anthropic       │ { name, description, input_schema }                    │
 *   │ Claude          │ assistant reply: content blocks of type "tool_use"     │
 *   │                 │ tool result:   user turn with content block            │
 *   │                 │                { type: "tool_result", tool_use_id }    │
 *   ├─────────────────┼────────────────────────────────────────────────────────┤
 *   │ Google Gemini   │ { function_declarations:                               │
 *   │                 │     [{ name, description, parameters }] }              │
 *   └─────────────────┴────────────────────────────────────────────────────────┘
 *
 * When we add a new provider (Anthropic, Gemini, OpenAI, ...), write an agent
 * loop in `providers/<vendor>.ts` that:
 *   1. Calls the relevant `toXxxTools(tools)` adapter below to serialize tools.
 *   2. Parses the vendor's tool-use payload format.
 *   3. Feeds tool results back in the vendor's expected shape.
 *
 * Tool definitions themselves are 100% portable — only the wire layer differs.
 */

import type { ToolInputSchema } from "../mcp/types.js";

export type AgenticToolDefinition = {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
};

/** OpenAI & all OpenAI-compatible APIs (xAI Grok, Groq, Together, etc.). */
export const toOpenAITools = (tools: AgenticToolDefinition[]) =>
  tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: t.inputSchema as unknown as Record<string, unknown>
    }
  }));

/**
 * Anthropic Claude. Not wired up yet — ready for when we add a Claude provider.
 * Reply parsing differs too: look for `content[].type === "tool_use"` and feed
 * results back as a user turn with `{ type: "tool_result", tool_use_id }`.
 */
export const toAnthropicTools = (tools: AgenticToolDefinition[]) =>
  tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.inputSchema
  }));

/**
 * Google Gemini. Not wired up yet — ready for when we add a Gemini provider.
 * Gemini wraps declarations in a single `tools: [{ function_declarations: [...] }]`.
 */
export const toGeminiFunctionDeclarations = (tools: AgenticToolDefinition[]) =>
  tools.map((t) => ({
    name: t.name,
    description: t.description,
    parameters: t.inputSchema as unknown as Record<string, unknown>
  }));
