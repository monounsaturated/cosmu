/**
 * Cosmu v2 Pipeline: Research Agent → Trader Agent → Deterministic Validator → Execution
 *
 * This module orchestrates the full decision cycle. Each phase is cleanly separated:
 * - Research: free-form LLM analysis (no structured output)
 * - Trader: structured JSON decision from LLM
 * - Validator: deterministic checks (non-LLM)
 * - Execution: via MCP tools
 */

import {
  tradingDecisionJsonSchema,
  tradingDecisionSchema,
  type TradingDecision
} from "@cosmu/shared";
import { storeLLMCall, type BotSetup } from "../lib/store.js";
import {
  getProvider,
  runXaiAgentLoop,
  runXaiResearchWithBrowsing,
  type AgenticTool,
  type AgentToolCallLog
} from "../providers/xai.js";
import { runNousAgentLoop } from "../providers/nous.js";
import { runOpenAIAgentLoop } from "../providers/openai.js";
import { runAnthropicAgentLoop } from "../providers/anthropic.js";
import { runHuggingFaceAgentLoop } from "../providers/huggingface.js";
import { runGoogleAgentLoop } from "../providers/google.js";
import { runMistralAgentLoop } from "../providers/mistral.js";
import type { LLMProvider, LLMMessage } from "../providers/llm.js";
import { getAgentFacingTools } from "../mcp/index.js";
import type { ToolContext } from "../mcp/types.js";

// ─── Types ───────────────────────────────────────────────────────────

export type ResearchResult = {
  rawText: string;
  provider: string;
  model: string;
};

export type TraderResult = {
  rawText: string;
  decision: TradingDecision;
  provider: string;
  model: string;
  toolCalls: AgentToolCallLog[];
  iterations: number;
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

// ─── Helpers ─────────────────────────────────────────────────────────

const extractJson = (text: string): string => {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) return fenced[1].trim();
  const braceStart = trimmed.indexOf("{");
  if (braceStart > 0) return trimmed.slice(braceStart);
  return trimmed;
};

const getResearchProvider = (bot: BotSetup): LLMProvider => {
  return getProvider(bot.modelProvider);
};

const getTraderProvider = (bot: BotSetup): LLMProvider => {
  return getProvider(bot.traderModelProvider);
};

const XAI_STABLE_FALLBACK_MODELS = [
  "grok-4.3",
  "grok-4.20-reasoning",
  "grok-3",
  "grok-3-fast",
  "grok-3-mini",
  "grok-3-mini-fast"
];

const buildModelCandidates = (providerName: string, primaryModel: string) => {
  if (providerName !== "xai") return [primaryModel];

  const candidates = [primaryModel];
  if (/-multi-agent/i.test(primaryModel)) {
    candidates.push(primaryModel.replace(/-multi-agent.*$/i, "-reasoning"));
  }
  candidates.push(...XAI_STABLE_FALLBACK_MODELS);
  return Array.from(new Set(candidates.filter(Boolean)));
};

const toErrorMessage = (error: unknown) => {
  if (!(error instanceof Error)) return String(error);

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
    } catch {
      details.push("payload=[unserializable]");
    }
  }

  return details.length > 0 ? `${error.message} (${details.join(", ")})` : error.message;
};

// ─── Research Agent ──────────────────────────────────────────────────

export const runResearchAgent = async (input: {
  bot: BotSetup;
  systemPrompt: string;
  userMessage: string;
  runId: string | null;
}): Promise<ResearchResult> => {
  const { bot, systemPrompt, userMessage, runId } = input;
  const provider = getResearchProvider(bot);
  const temperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;

  const messages: LLMMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage }
  ];

  // xAI research goes through the Responses API so the model can actually browse
  // (web_search + x_search). Chat Completions on xAI doesn't support those tools,
  // which is what caused Grok to fabricate tweets. Other providers use chat().
  const useXaiBrowsing = provider.name === "xai";
  const baseStrategyLabel = useXaiBrowsing ? "responses_api+browsing" : "text";
  const modelCandidates = buildModelCandidates(provider.name, bot.modelIdentifier);

  let lastError: unknown;
  const attemptErrors: string[] = [];
  let attempt = 0;

  for (const modelCandidate of modelCandidates) {
    attempt += 1;
    const start = Date.now();
    const strategyLabel = `${baseStrategyLabel}/${modelCandidate}`;
    try {
      let rawText: string;
      let model: string;
      let usage: { inputTokens: number; outputTokens: number } | null;

      if (useXaiBrowsing) {
        const result = await runXaiResearchWithBrowsing({
          model: modelCandidate,
          systemPrompt,
          userMessage,
          temperature
        });
        rawText = result.rawText;
        model = result.model;
        usage = result.usage;
      } else {
        const response = await provider.chat({
          model: modelCandidate,
          messages,
          temperature
        });
        rawText = response.content;
        model = response.model;
        usage = response.usage;
      }

      if (runId) {
        void storeLLMCall({
          runId,
          phase: "research",
          provider: provider.name,
          model,
          inputMessages: messages,
          outputText: rawText,
          inputTokens: usage?.inputTokens ?? null,
          outputTokens: usage?.outputTokens ?? null,
          latencyMs: Date.now() - start,
          attempt,
          strategy: strategyLabel,
          error: null
        });
      }

      return {
        rawText,
        provider: provider.name,
        model
      };
    } catch (error) {
      lastError = error;
      const errorMessage = toErrorMessage(error);
      attemptErrors.push(`${modelCandidate}: ${errorMessage}`);

      if (runId) {
        void storeLLMCall({
          runId,
          phase: "research",
          provider: provider.name,
          model: modelCandidate,
          inputMessages: messages,
          outputText: null,
          inputTokens: null,
          outputTokens: null,
          latencyMs: Date.now() - start,
          attempt,
          strategy: strategyLabel,
          error: errorMessage
        });
      }
    }
  }

  const recentFailures = attemptErrors.slice(-3).join(" | ");
  throw lastError instanceof Error
    ? new Error(
        `Research request failed for ${bot.modelIdentifier}. Recent: ${recentFailures || lastError.message}`,
        { cause: lastError }
      )
    : new Error("Research request failed");
};

// ─── Trader Agent (agentic — uses tool-use loop) ─────────────────────

type TraderAttemptStrategy = {
  label: string;
  useTemperature: boolean;
  responseFormat?: Record<string, unknown>;
};

const TRADER_ATTEMPT_STRATEGIES: TraderAttemptStrategy[] = [
  {
    label: "tools+json_schema",
    useTemperature: false,
    responseFormat: {
      type: "json_schema",
      json_schema: {
        name: "TradingDecision",
        schema: tradingDecisionJsonSchema,
        strict: true
      }
    }
  },
  { label: "tools+json_object", useTemperature: false, responseFormat: { type: "json_object" } },
  { label: "tools+no_format", useTemperature: false }
];

const buildAgenticTools = (toolContext: ToolContext): AgenticTool[] =>
  getAgentFacingTools().map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema!,
    execute: (input: unknown) => tool.execute(input, toolContext)
  }));

const runAgentLoop = (input: {
  providerName: string;
  model: string;
  systemPrompt: string;
  userMessage: string;
  tools: AgenticTool[];
  temperature?: number;
  responseFormat?: Record<string, unknown>;
  maxIterations?: number;
}) => {
  const { providerName, ...rest } = input;
  if (providerName === "xai") return runXaiAgentLoop(rest);
  if (providerName === "nous") return runNousAgentLoop(rest);
  if (providerName === "openai") return runOpenAIAgentLoop(rest);
  if (providerName === "huggingface") return runHuggingFaceAgentLoop(rest);
  if (providerName === "google") return runGoogleAgentLoop(rest);
  if (providerName === "mistral") return runMistralAgentLoop(rest);
  if (providerName === "anthropic") {
    const { responseFormat: _responseFormat, ...anthropicInput } = rest;
    return runAnthropicAgentLoop(anthropicInput);
  }
  throw new Error(`Provider ${providerName} does not support trader tool loops yet`);
};

export const runTraderAgent = async (input: {
  bot: BotSetup;
  systemPrompt: string;
  userMessage: string;
  runId: string | null;
  toolContext: ToolContext;
}): Promise<TraderResult> => {
  const { bot, systemPrompt, userMessage, runId, toolContext } = input;
  const provider = getTraderProvider(bot);
  const configuredTemperature =
    typeof bot.traderModelSettings.temperature === "number" ? bot.traderModelSettings.temperature : undefined;

  const tools = buildAgenticTools(toolContext);
  const loggedMessages: LLMMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage }
  ];

  let lastError: unknown;
  let lastRawText = "";
  const attemptErrors: string[] = [];
  let attempt = 0;
  const modelCandidates = buildModelCandidates(provider.name, bot.traderModelIdentifier);

  for (const modelCandidate of modelCandidates) {
    for (const strategy of TRADER_ATTEMPT_STRATEGIES) {
      attempt += 1;
      const start = Date.now();
      const strategyLabel = `${strategy.label}/${modelCandidate}`;

      try {
        const result = await runAgentLoop({
          providerName: provider.name,
          model: modelCandidate,
          systemPrompt,
          userMessage,
          tools,
          temperature: strategy.useTemperature ? configuredTemperature : undefined,
          responseFormat: strategy.responseFormat,
          maxIterations: 6
        });

        if (result.finishReason === "tool_iterations_exhausted") {
          throw new Error(
            `Trader exhausted tool iterations (${result.iterations}) without producing a final decision`
          );
        }

        if (!result.content || !result.content.trim()) {
          throw new Error("Trader returned empty final response");
        }

        lastRawText = result.content;
        const jsonText = extractJson(result.content);
        let decision: TradingDecision;
        try {
          decision = tradingDecisionSchema.parse(JSON.parse(jsonText));
        } catch (parseError) {
          throw new DecisionParseError(
            `Invalid JSON decision (strategy: ${strategyLabel})`,
            result.content,
            { cause: parseError }
          );
        }

        if (runId) {
          void storeLLMCall({
            runId,
            phase: "trader",
            provider: provider.name,
            model: result.model,
            inputMessages: {
              messages: loggedMessages,
              tools: tools.map((t) => ({ name: t.name, description: t.description })),
              toolCalls: result.toolCalls,
              iterations: result.iterations
            } as unknown,
            outputText: result.content,
            inputTokens: result.usage?.inputTokens ?? null,
            outputTokens: result.usage?.outputTokens ?? null,
            latencyMs: Date.now() - start,
            attempt,
            strategy: strategyLabel,
            error: null
          });
        }

        return {
          rawText: result.content,
          decision,
          provider: provider.name,
          model: result.model,
          toolCalls: result.toolCalls,
          iterations: result.iterations
        };
      } catch (error) {
        lastError = error;
        const errorMessage = error instanceof DecisionParseError ? error.message : toErrorMessage(error);
        if (error instanceof DecisionParseError) {
          lastRawText = error.rawText;
        }
        attemptErrors.push(`${strategyLabel}: ${errorMessage}`);

        if (runId) {
          void storeLLMCall({
            runId,
            phase: "trader",
            provider: provider.name,
            model: modelCandidate,
            inputMessages: loggedMessages,
            outputText: error instanceof DecisionParseError ? error.rawText : null,
            inputTokens: null,
            outputTokens: null,
            latencyMs: Date.now() - start,
            attempt,
            strategy: strategyLabel,
            error: errorMessage
          });
        }
      }
    }
  }

  const recentFailures = attemptErrors.slice(-3).join(" | ");
  if (lastError instanceof DecisionParseError) {
    throw new DecisionParseError(
      `All trader attempts returned invalid decisions for ${bot.traderModelIdentifier}. Recent: ${recentFailures}`,
      lastRawText || lastError.rawText,
      { cause: lastError }
    );
  }
  throw new Error(
    `All trader attempts failed for ${bot.traderModelIdentifier}. Recent: ${recentFailures}`,
    { cause: lastError }
  );
};

// ─── Symbol Extraction ───────────────────────────────────────────────

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
