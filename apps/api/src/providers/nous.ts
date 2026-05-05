import OpenAI from "openai";
import { env } from "../env.js";
import type { LLMChatInput, LLMProvider, LLMResponse } from "./llm.js";

const getNousBaseUrl = () => env.NOUS_BASE_URL ?? "https://portal.nousresearch.com/v1";

const createClient = () => {
  if (!env.NOUS_API_KEY) {
    throw new Error("NOUS_API_KEY is not configured");
  }

  return new OpenAI({
    apiKey: env.NOUS_API_KEY,
    baseURL: getNousBaseUrl()
  });
};

export const nousProvider: LLMProvider = {
  name: "nous",
  chat: async (input: LLMChatInput): Promise<LLMResponse> => {
    const client = createClient();
    const completion = await client.chat.completions.create({
      model: input.model,
      ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
      messages: input.messages.map((message) => ({ role: message.role, content: message.content })),
      ...(input.responseFormat ? { response_format: input.responseFormat } : {})
    } as Parameters<typeof client.chat.completions.create>[0]);

    if (!("choices" in completion)) {
      throw new Error("Nous returned a stream response unexpectedly");
    }

    const content = completion.choices[0]?.message?.content;
    if (!content) {
      throw new Error(`Nous returned no content (model: ${input.model})`);
    }

    return {
      content,
      usage: completion.usage
        ? {
            inputTokens: completion.usage.prompt_tokens ?? 0,
            outputTokens: completion.usage.completion_tokens ?? 0
          }
        : null,
      model: input.model,
      strategy: input.responseFormat ? (input.responseFormat as { type?: string }).type ?? "unknown" : "text"
    };
  }
};

export const listNousModels = async () => {
  if (!env.NOUS_API_KEY) {
    throw new Error("NOUS_API_KEY is not configured");
  }

  const response = await fetch(`${getNousBaseUrl().replace(/\/$/, "")}/models`, {
    headers: { Authorization: `Bearer ${env.NOUS_API_KEY}` },
    signal: AbortSignal.timeout(5000)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Nous models list failed: ${response.status} ${text}`);
  }

  const data = await response.json();
  const rows: Array<{ id?: unknown; created?: unknown }> = Array.isArray(data?.data) ? data.data : [];
  return rows
    .map((row) => ({
      id: String(row.id ?? ""),
      created: typeof row.created === "number" ? row.created : null
    }))
    .filter((row) => row.id.length > 0);
};
