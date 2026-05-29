// module: Factory for OpenAI-compatible chat providers.
import OpenAI from "openai";
import { env } from "../env.js";
import type { ToolInputSchema } from "../mcp/types.js";
import { toOpenAITools } from "./tool-adapters.js";
import type { LLMChatInput, LLMProvider, LLMResponse } from "./llm.js";
import type { AgenticTool, AgenticChatResult, AgentToolCallLog } from "./xai.js";

type ProviderName = "openai" | "huggingface" | "nous" | "google" | "mistral";

type ProviderConfig = {
  apiKey: string | undefined;
  baseURL?: string;
  label: string;
};

const getProviderConfig = (provider: ProviderName): ProviderConfig => {
  if (provider === "openai") {
    return {
      apiKey: env.OPENAI_API_KEY,
      baseURL: env.OPENAI_BASE_URL,
      label: "OpenAI"
    };
  }
  if (provider === "huggingface") {
    return {
      apiKey: env.HUGGINGFACE_API_KEY,
      baseURL: env.HUGGINGFACE_BASE_URL ?? "https://router.huggingface.co/v1",
      label: "Hugging Face"
    };
  }
  if (provider === "google") {
    return {
      apiKey: env.GOOGLE_API_KEY,
      baseURL: env.GOOGLE_BASE_URL ?? "https://generativelanguage.googleapis.com/v1beta/openai/",
      label: "Google"
    };
  }
  if (provider === "mistral") {
    return {
      apiKey: env.MISTRAL_API_KEY,
      baseURL: env.MISTRAL_BASE_URL ?? "https://api.mistral.ai/v1",
      label: "Mistral"
    };
  }
  return {
    apiKey: env.NOUS_API_KEY,
    baseURL: env.NOUS_BASE_URL ?? "https://portal.nousresearch.com/v1",
    label: "Nous"
  };
};

const createClient = (provider: ProviderName) => {
  const config = getProviderConfig(provider);
  if (!config.apiKey) {
    throw new Error(`${config.label} API key is not configured`);
  }
  return new OpenAI({
    apiKey: config.apiKey,
    ...(config.baseURL ? { baseURL: config.baseURL } : {})
  });
};

export const createOpenAiCompatibleProvider = (provider: ProviderName): LLMProvider => ({
  name: provider,
  chat: async (input: LLMChatInput): Promise<LLMResponse> => {
    const client = createClient(provider);
    const completion = await client.chat.completions.create({
      model: input.model,
      ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
      messages: input.messages.map((message) => ({ role: message.role, content: message.content })),
      ...(input.responseFormat ? { response_format: input.responseFormat } : {})
    } as Parameters<typeof client.chat.completions.create>[0]);

    if (!("choices" in completion)) {
      throw new Error(`${provider} returned a stream response unexpectedly`);
    }

    const content = completion.choices[0]?.message?.content;
    if (!content) {
      throw new Error(`${provider} returned no content (model: ${input.model})`);
    }

    return {
      content,
      usage: completion.usage
        ? {
            inputTokens: completion.usage.prompt_tokens ?? 0,
            outputTokens: completion.usage.completion_tokens ?? 0
          }
        : null,
      model: completion.model ?? input.model,
      strategy: input.responseFormat ? (input.responseFormat as { type?: string }).type ?? "unknown" : "text"
    };
  }
});

export const listOpenAiCompatibleModels = async (provider: ProviderName) => {
  const client = createClient(provider);
  const models = await client.models.list();
  return models.data
    .map((model) => ({
      id: String(model.id ?? ""),
      created: typeof model.created === "number" ? model.created : null
    }))
    .filter((model) => model.id.length > 0);
};

export const runOpenAiCompatibleAgentLoop = async (input: {
  provider: ProviderName;
  model: string;
  systemPrompt: string;
  userMessage: string;
  tools: AgenticTool[];
  temperature?: number;
  responseFormat?: Record<string, unknown>;
  maxIterations?: number;
}): Promise<AgenticChatResult> => {
  const client = createClient(input.provider);
  const max = input.maxIterations ?? 6;
  const toolMap = new Map(input.tools.map((tool) => [tool.name, tool]));
  const openAiTools = toOpenAITools(input.tools as Array<AgenticTool & { inputSchema: ToolInputSchema }>);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const conversation: any[] = [
    { role: "system", content: input.systemPrompt },
    { role: "user", content: input.userMessage }
  ];
  const toolCalls: AgentToolCallLog[] = [];
  let totalPromptTokens = 0;
  let totalCompletionTokens = 0;
  let finalModel = input.model;
  let iterations = 0;

  for (iterations = 1; iterations <= max; iterations++) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const completion: any = await client.chat.completions.create({
      model: input.model,
      messages: conversation,
      tools: openAiTools,
      tool_choice: "auto",
      ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
      ...(input.responseFormat ? { response_format: input.responseFormat } : {})
    } as Parameters<typeof client.chat.completions.create>[0]);

    if (!("choices" in completion)) {
      throw new Error(`${input.provider} returned a stream response unexpectedly`);
    }

    finalModel = completion.model ?? finalModel;
    if (completion.usage) {
      totalPromptTokens += completion.usage.prompt_tokens ?? 0;
      totalCompletionTokens += completion.usage.completion_tokens ?? 0;
    }

    const message = completion.choices[0]?.message;
    if (!message) {
      return {
        content: "",
        model: finalModel,
        usage: { inputTokens: totalPromptTokens, outputTokens: totalCompletionTokens },
        iterations,
        toolCalls,
        finalConversation: conversation,
        finishReason: "empty"
      };
    }

    const assistantEntry: Record<string, unknown> = {
      role: "assistant",
      content: message.content ?? null
    };
    if (Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
      assistantEntry.tool_calls = message.tool_calls;
    }
    conversation.push(assistantEntry);

    const calls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
    if (calls.length === 0) {
      return {
        content: String(message.content ?? ""),
        model: finalModel,
        usage: { inputTokens: totalPromptTokens, outputTokens: totalCompletionTokens },
        iterations,
        toolCalls,
        finalConversation: conversation,
        finishReason: "stop"
      };
    }

    for (const call of calls) {
      const name = String(call.function?.name ?? "");
      let parsedInput: unknown = {};
      try {
        parsedInput = JSON.parse(String(call.function?.arguments ?? "{}"));
      } catch {
        parsedInput = {};
      }

      const tool = toolMap.get(name);
      const start = Date.now();
      let output: unknown;
      let error: string | null = null;
      if (!tool) {
        error = `Unknown tool: ${name}`;
        output = { error };
      } else {
        try {
          output = await tool.execute(parsedInput);
        } catch (err) {
          error = err instanceof Error ? err.message : String(err);
          output = { error };
        }
      }

      toolCalls.push({ tool: name, input: parsedInput, output, latencyMs: Date.now() - start, error });
      conversation.push({
        role: "tool",
        tool_call_id: call.id,
        content: JSON.stringify(output)
      });
    }
  }

  return {
    content: "",
    model: finalModel,
    usage: { inputTokens: totalPromptTokens, outputTokens: totalCompletionTokens },
    iterations: max,
    toolCalls,
    finalConversation: conversation,
    finishReason: "tool_iterations_exhausted"
  };
};
