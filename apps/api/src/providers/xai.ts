import OpenAI from "openai";
import {
  tradingDecisionJsonSchema,
  tradingDecisionSchema,
  type TradingDecision
} from "@cosmu/shared";
import { env } from "../env.js";
import type { BotSetup } from "../lib/store.js";
import type { LLMProvider, LLMChatInput, LLMResponse, LLMMessage } from "./llm.js";
import type { ToolInputSchema } from "../mcp/types.js";
import { toOpenAITools } from "./tool-adapters.js";

const client = new OpenAI({
  apiKey: env.XAI_API_KEY,
  baseURL: "https://api.x.ai/v1"
});

// xAI Agent Tools API — server-hosted tools that execute on xAI's side (no local schemas).
// Adding these to the `tools` array of a chat completion lets Grok browse X and the web.
// The model decides when to invoke them; they're always available, never forced.
// Ref: https://docs.x.ai/docs/guides/tools/overview
const XAI_SERVER_TOOLS = [
  { type: "x_search" },
  { type: "web_search" }
];

// ─── LLM Provider Interface Implementation ──────────────────────────

export const xaiProvider: LLMProvider = {
  name: "xai",
  chat: async (input: LLMChatInput): Promise<LLMResponse> => {
    const completion = await client.chat.completions.create({
      model: input.model,
      ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
      messages: input.messages.map((m) => ({ role: m.role, content: m.content })),
      // Always expose xAI's server-hosted search tools to research-phase calls so Grok
      // can actually browse X / the web when the prompt asks for current news.
      tools: XAI_SERVER_TOOLS as unknown as Parameters<typeof client.chat.completions.create>[0]["tools"],
      ...(input.responseFormat ? { response_format: input.responseFormat } : {})
    } as Parameters<typeof client.chat.completions.create>[0]);

    if (!("choices" in completion)) {
      throw new Error("xAI returned a stream response unexpectedly");
    }

    const content = completion.choices[0]?.message?.content;
    if (!content) {
      throw new Error(`xAI returned no content (model: ${input.model})`);
    }

    const usage = completion.usage
      ? {
          inputTokens: completion.usage.prompt_tokens ?? 0,
          outputTokens: completion.usage.completion_tokens ?? 0
        }
      : null;

    return {
      content,
      usage,
      model: input.model,
      strategy: input.responseFormat
        ? (input.responseFormat as { type?: string }).type ?? "unknown"
        : "text"
    };
  }
};

// ─── Provider Factory ────────────────────────────────────────────────

const providers: Record<string, LLMProvider> = {
  xai: xaiProvider
};

export const getProvider = (name: string): LLMProvider => {
  const provider = providers[name];
  if (!provider) {
    throw new Error(`Unknown LLM provider: ${name}. Available: ${Object.keys(providers).join(", ")}`);
  }
  return provider;
};

export const registerProvider = (provider: LLMProvider) => {
  providers[provider.name] = provider;
};

// ─── Legacy Functions (used by existing run-bot.ts until pipeline.ts takes over) ─

type DecisionRequest = {
  bot: BotSetup;
  systemPrompt: string;
  userMessage: string;
};

export class DecisionParseError extends Error {
  rawText: string;
  constructor(message: string, rawText: string, options?: { cause?: unknown }) {
    super(message);
    this.name = "DecisionParseError";
    this.rawText = rawText;
    if (options?.cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = options.cause;
    }
  }
}

const extractJson = (text: string): string => {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) return fenced[1].trim();
  const braceStart = trimmed.indexOf("{");
  if (braceStart > 0) return trimmed.slice(braceStart);
  return trimmed;
};

type ResponseStrategy = {
  label: string;
  format?: Record<string, unknown>;
};

type TemperatureStrategy = {
  label: string;
  includeTemperature: boolean;
};

const STRATEGIES: ResponseStrategy[] = [
  {
    label: "json_schema",
    format: {
      type: "json_schema",
      json_schema: {
        name: "TradingDecision",
        schema: tradingDecisionJsonSchema,
        strict: true
      }
    }
  },
  { label: "json_object", format: { type: "json_object" } },
  { label: "text" }
];

const TEMPERATURE_STRATEGIES: TemperatureStrategy[] = [
  { label: "with_temperature", includeTemperature: true },
  { label: "without_temperature", includeTemperature: false }
];

const XAI_STABLE_FALLBACK_MODELS = [
  "grok-4.20-reasoning",
  "grok-3",
  "grok-3-fast",
  "grok-3-mini",
  "grok-3-mini-fast"
];

const XAI_NON_CHAT_MODEL_PATTERNS = [
  /-multi-agent/i,
  /-vision/i,
  /-image/i,
  /-audio/i
];

const isLikelyChatModel = (modelId: string) =>
  modelId.length > 0 && !XAI_NON_CHAT_MODEL_PATTERNS.some((pattern) => pattern.test(modelId));

const buildModelCandidates = (primaryModel: string) => {
  const candidates: string[] = [primaryModel];
  if (/-multi-agent/i.test(primaryModel)) {
    candidates.push(primaryModel.replace(/-multi-agent.*$/i, "-reasoning"));
  }
  candidates.push(...XAI_STABLE_FALLBACK_MODELS);
  return Array.from(new Set(candidates.filter(Boolean)));
};

const toErrorMessage = (error: unknown) => {
  if (error instanceof Error) {
    const details: string[] = [];
    const status = (error as { status?: unknown }).status;
    const code = (error as { code?: unknown }).code;
    const type = (error as { type?: unknown }).type;
    const payload = (error as { error?: unknown }).error;
    if (typeof status === "number") details.push(`status=${status}`);
    if (typeof code === "string" && code.length > 0) details.push(`code=${code}`);
    if (typeof type === "string" && type.length > 0) details.push(`type=${type}`);
    if (payload !== undefined) {
      try {
        const serialized = JSON.stringify(payload);
        if (serialized !== "{}") details.push(`payload=${serialized}`);
      } catch { details.push("payload=[unserializable]"); }
    }
    return details.length > 0 ? `${error.message} (${details.join(", ")})` : error.message;
  }
  return String(error);
};

export const requestDecision = async ({
  bot,
  systemPrompt,
  userMessage
}: DecisionRequest): Promise<{ rawText: string; decision: TradingDecision }> => {
  let lastError: unknown;
  const attemptErrors: string[] = [];
  const configuredTemperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;
  const modelCandidates = buildModelCandidates(bot.modelIdentifier);

  for (const modelIdentifier of modelCandidates) {
    for (const strategy of STRATEGIES) {
      for (const tempStrategy of TEMPERATURE_STRATEGIES) {
        try {
          const completion = await client.chat.completions.create({
            model: modelIdentifier,
            ...(tempStrategy.includeTemperature && configuredTemperature !== undefined
              ? { temperature: configuredTemperature }
              : {}),
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: userMessage }
            ],
            ...(strategy.format ? { response_format: strategy.format } : {})
          } as Parameters<typeof client.chat.completions.create>[0]);

          if (!("choices" in completion)) {
            throw new Error("xAI returned a stream response unexpectedly");
          }

          const rawText = completion.choices[0]?.message?.content;
          if (!rawText) {
            throw new Error(
              `xAI returned no content (model: ${modelIdentifier}, strategy: ${strategy.label}, temperature: ${tempStrategy.label})`
            );
          }

          const jsonText = extractJson(rawText);
          let decision: TradingDecision;
          try {
            decision = tradingDecisionSchema.parse(JSON.parse(jsonText));
          } catch (parseError) {
            throw new DecisionParseError(
              `xAI returned invalid JSON decision (model: ${modelIdentifier}, strategy: ${strategy.label}, temperature: ${tempStrategy.label})`,
              rawText,
              { cause: parseError }
            );
          }

          if (modelIdentifier !== bot.modelIdentifier) {
            console.warn(
              `[xAI] Using fallback model ${modelIdentifier} for bot ${bot.id} (configured ${bot.modelIdentifier})`
            );
          }

          return { rawText, decision };
        } catch (error) {
          lastError = error;
          if (error instanceof DecisionParseError) throw error;
          const message = toErrorMessage(error);
          const attemptLabel = `${modelIdentifier}/${strategy.label}/${tempStrategy.label}`;
          attemptErrors.push(`${attemptLabel}: ${message}`);
          console.warn(`Decision attempt failed (${attemptLabel}): ${message}`);
        }
      }
    }
  }

  const recentFailures = attemptErrors.slice(-3).join(" | ");
  const message = recentFailures.length > 0
    ? `All xAI decision attempts failed for ${bot.modelIdentifier}. Recent failures: ${recentFailures}`
    : `All xAI decision attempts failed for ${bot.modelIdentifier}.`;
  throw new Error(message, { cause: lastError });
};

export const extractCandidateSymbols = (rawText: string, venueSymbols: string[]): string[] => {
  const venueSet = new Set(venueSymbols.map((s) => s.toUpperCase()));
  const matches = rawText.match(/[A-Z]{2,10}USD[TC]/g);
  if (!matches) return [];
  const unique = new Set<string>();
  for (const m of matches) {
    if (venueSet.has(m) && m !== "USDTUSDT" && m !== "USDCUSDC") unique.add(m);
  }
  return Array.from(unique);
};

export const requestResearchPhase = async ({
  bot,
  systemPrompt,
  userMessage
}: DecisionRequest): Promise<{ rawText: string }> => {
  let lastError: unknown;
  const attemptErrors: string[] = [];
  const configuredTemperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;
  const modelCandidates = buildModelCandidates(bot.modelIdentifier);

  for (const modelIdentifier of modelCandidates) {
    for (const tempStrategy of TEMPERATURE_STRATEGIES) {
      try {
        const completion = await client.chat.completions.create({
          model: modelIdentifier,
          ...(tempStrategy.includeTemperature && configuredTemperature !== undefined
            ? { temperature: configuredTemperature }
            : {}),
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: userMessage }
          ]
        } as Parameters<typeof client.chat.completions.create>[0]);

        if (!("choices" in completion)) {
          throw new Error("xAI returned a stream response unexpectedly");
        }

        const rawText = completion.choices[0]?.message?.content;
        if (!rawText) {
          throw new Error(
            `xAI returned no content (model: ${modelIdentifier}, temperature: ${tempStrategy.label})`
          );
        }

        if (modelIdentifier !== bot.modelIdentifier) {
          console.warn(
            `[xAI] Research phase using fallback model ${modelIdentifier} for bot ${bot.id} (configured ${bot.modelIdentifier})`
          );
        }

        return { rawText };
      } catch (error) {
        lastError = error;
        const message = toErrorMessage(error);
        const attemptLabel = `${modelIdentifier}/${tempStrategy.label}`;
        attemptErrors.push(`${attemptLabel}: ${message}`);
        console.warn(`Research attempt failed (${attemptLabel}): ${message}`);
      }
    }
  }

  const recentFailures = attemptErrors.slice(-3).join(" | ");
  const message = recentFailures.length > 0
    ? `All xAI research attempts failed for ${bot.modelIdentifier}. Recent failures: ${recentFailures}`
    : `All xAI research attempts failed for ${bot.modelIdentifier}.`;
  throw new Error(message, { cause: lastError });
};

// ─── Agentic Tool-Use Loop (used by trader phase) ───────────────────

export type AgenticTool = {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
  execute: (input: unknown) => Promise<unknown>;
};

export type AgentToolCallLog = {
  tool: string;
  input: unknown;
  output: unknown;
  latencyMs: number;
  error: string | null;
};

export type AgenticChatResult = {
  content: string;
  model: string;
  usage: { inputTokens: number; outputTokens: number } | null;
  iterations: number;
  toolCalls: AgentToolCallLog[];
  finalConversation: unknown[];
  finishReason: "stop" | "tool_iterations_exhausted" | "empty";
};

/**
 * Run a tool-use agent loop against xAI (OpenAI-compatible).
 * The model can call tools between turns; we execute them and feed results back.
 * Stops when the model returns a message with no tool_calls (final answer) or when
 * maxIterations is reached.
 */
export const runXaiAgentLoop = async (input: {
  model: string;
  systemPrompt: string;
  userMessage: string;
  tools: AgenticTool[];
  temperature?: number;
  responseFormat?: Record<string, unknown>;
  maxIterations?: number;
}): Promise<AgenticChatResult> => {
  const max = input.maxIterations ?? 6;
  const toolMap = new Map(input.tools.map((t) => [t.name, t]));
  // Merge local function tools with xAI's server-hosted tools so the trader can optionally
  // call x_search / web_search when it needs fresh info (e.g. unknown ticker, news check).
  // The model decides when — server tools execute on xAI's side with no local handler.
  const openAiTools = [
    ...toOpenAITools(input.tools),
    ...(XAI_SERVER_TOOLS as unknown as ReturnType<typeof toOpenAITools>)
  ];

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
    const baseParams: Record<string, unknown> = {
      model: input.model,
      messages: conversation,
      tools: openAiTools,
      tool_choice: "auto"
    };
    if (input.temperature !== undefined) baseParams.temperature = input.temperature;
    if (input.responseFormat) baseParams.response_format = input.responseFormat;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const completion: any = await client.chat.completions.create(baseParams as any);

    if (!completion?.choices) {
      throw new Error("xAI returned a stream response unexpectedly");
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const fn = (call as any).function;
      const name = String(fn?.name ?? "");
      let parsedInput: unknown = {};
      try {
        parsedInput = JSON.parse(String(fn?.arguments ?? "{}"));
      } catch {
        parsedInput = {};
      }

      const tool = toolMap.get(name);
      const start = Date.now();
      let output: unknown = null;
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

      toolCalls.push({
        tool: name,
        input: parsedInput,
        output,
        latencyMs: Date.now() - start,
        error
      });

      conversation.push({
        role: "tool",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        tool_call_id: (call as any).id,
        content: JSON.stringify(output)
      });
    }
  }

  // Max iterations reached without a final text response.
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

export const listXaiModels = async () => {
  const response = await fetch("https://api.x.ai/v1/models", {
    headers: { Authorization: `Bearer ${env.XAI_API_KEY}` },
    signal: AbortSignal.timeout(5000)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`xAI models list failed: ${response.status} ${text}`);
  }

  const data = await response.json();
  const rows: Array<{ id?: unknown; created?: unknown }> = Array.isArray(data?.data) ? data.data : [];

  return rows
    .map((row) => ({
      id: String(row.id ?? ""),
      created: typeof row.created === "number" ? row.created : null
    }))
    .filter((row: { id: string; created: number | null }) => isLikelyChatModel(row.id));
};
