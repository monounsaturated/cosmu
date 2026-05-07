import { env } from "../env.js";
import type { LLMChatInput, LLMProvider, LLMResponse, LLMMessage } from "./llm.js";
import type { AgenticChatResult, AgenticTool, AgentToolCallLog } from "./xai.js";

const getAnthropicBaseUrl = () => env.ANTHROPIC_BASE_URL ?? "https://api.anthropic.com/v1";

const requireAnthropicApiKey = () => {
  if (!env.ANTHROPIC_API_KEY) {
    throw new Error("ANTHROPIC_API_KEY is not configured");
  }
};

const headers = () => {
  requireAnthropicApiKey();
  return {
    "x-api-key": env.ANTHROPIC_API_KEY!,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
  };
};

const splitSystemMessages = (messages: LLMMessage[]) => {
  const system = messages
    .filter((message) => message.role === "system")
    .map((message) => message.content)
    .join("\n\n")
    .trim();
  const conversational = messages
    .filter((message) => message.role !== "system")
    .map((message) => ({ role: message.role as "user" | "assistant", content: message.content }));
  return { system: system || undefined, messages: conversational };
};

const extractText = (response: unknown) => {
  const content = (response as { content?: unknown }).content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const type = (part as { type?: unknown }).type;
      const text = (part as { text?: unknown }).text;
      return type === "text" && typeof text === "string" ? text : "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
};

const readUsage = (response: unknown) => {
  const usage = (response as { usage?: { input_tokens?: number; output_tokens?: number } }).usage;
  return usage
    ? {
        inputTokens: usage.input_tokens ?? 0,
        outputTokens: usage.output_tokens ?? 0
      }
    : null;
};

export const anthropicProvider: LLMProvider = {
  name: "anthropic",
  chat: async (input: LLMChatInput): Promise<LLMResponse> => {
    const split = splitSystemMessages(input.messages);
    const response = await fetch(`${getAnthropicBaseUrl().replace(/\/$/, "")}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        model: input.model,
        max_tokens: 4096,
        ...(split.system ? { system: split.system } : {}),
        ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
        messages: split.messages
      })
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(`Anthropic request failed: ${response.status} ${JSON.stringify(data)}`);
    }

    const content = extractText(data);
    if (!content) {
      throw new Error(`Anthropic returned no content (model: ${input.model})`);
    }

    return {
      content,
      usage: readUsage(data),
      model: String((data as { model?: unknown }).model ?? input.model),
      strategy: "messages"
    };
  }
};

export const listAnthropicModels = async () => {
  const response = await fetch(`${getAnthropicBaseUrl().replace(/\/$/, "")}/models`, {
    headers: headers(),
    signal: AbortSignal.timeout(5000)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(`Anthropic models list failed: ${response.status} ${JSON.stringify(data)}`);
  }
  const rows: Array<{ id?: unknown; created_at?: unknown }> = Array.isArray(data?.data) ? data.data : [];
  return rows
    .map((row) => ({
      id: String(row.id ?? ""),
      created: row.created_at ? Date.parse(String(row.created_at)) / 1000 : null
    }))
    .filter((row) => row.id.length > 0);
};

export const runAnthropicAgentLoop = async (input: {
  model: string;
  systemPrompt: string;
  userMessage: string;
  tools: AgenticTool[];
  temperature?: number;
  maxIterations?: number;
}): Promise<AgenticChatResult> => {
  const max = input.maxIterations ?? 6;
  const toolMap = new Map(input.tools.map((tool) => [tool.name, tool]));
  const tools = input.tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema
  }));
  const messages: Array<Record<string, unknown>> = [{ role: "user", content: input.userMessage }];
  const toolCalls: AgentToolCallLog[] = [];
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let finalModel = input.model;
  let iterations = 0;

  for (iterations = 1; iterations <= max; iterations++) {
    const response = await fetch(`${getAnthropicBaseUrl().replace(/\/$/, "")}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        model: input.model,
        max_tokens: 4096,
        system: input.systemPrompt,
        messages,
        tools,
        ...(input.temperature !== undefined ? { temperature: input.temperature } : {})
      })
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(`Anthropic request failed: ${response.status} ${JSON.stringify(data)}`);
    }

    finalModel = String((data as { model?: unknown }).model ?? finalModel);
    const usage = readUsage(data);
    totalInputTokens += usage?.inputTokens ?? 0;
    totalOutputTokens += usage?.outputTokens ?? 0;

    const content = (data as { content?: unknown }).content;
    if (!Array.isArray(content)) {
      return {
        content: "",
        model: finalModel,
        usage: { inputTokens: totalInputTokens, outputTokens: totalOutputTokens },
        iterations,
        toolCalls,
        finalConversation: messages,
        finishReason: "empty"
      };
    }

    messages.push({ role: "assistant", content });
    const requestedTools = content.filter((part) => {
      return Boolean(part && typeof part === "object" && (part as { type?: unknown }).type === "tool_use");
    }) as Array<{ id?: unknown; name?: unknown; input?: unknown }>;

    if (requestedTools.length === 0) {
      return {
        content: extractText(data),
        model: finalModel,
        usage: { inputTokens: totalInputTokens, outputTokens: totalOutputTokens },
        iterations,
        toolCalls,
        finalConversation: messages,
        finishReason: "stop"
      };
    }

    const toolResults = [];
    for (const call of requestedTools) {
      const name = String(call.name ?? "");
      const tool = toolMap.get(name);
      const start = Date.now();
      let output: unknown;
      let error: string | null = null;
      if (!tool) {
        error = `Unknown tool: ${name}`;
        output = { error };
      } else {
        try {
          output = await tool.execute(call.input ?? {});
        } catch (err) {
          error = err instanceof Error ? err.message : String(err);
          output = { error };
        }
      }

      toolCalls.push({ tool: name, input: call.input ?? {}, output, latencyMs: Date.now() - start, error });
      toolResults.push({
        type: "tool_result",
        tool_use_id: String(call.id ?? ""),
        content: JSON.stringify(output),
        is_error: Boolean(error)
      });
    }
    messages.push({ role: "user", content: toolResults });
  }

  return {
    content: "",
    model: finalModel,
    usage: { inputTokens: totalInputTokens, outputTokens: totalOutputTokens },
    iterations: max,
    toolCalls,
    finalConversation: messages,
    finishReason: "tool_iterations_exhausted"
  };
};
