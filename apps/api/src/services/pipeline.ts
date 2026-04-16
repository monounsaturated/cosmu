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
import type { BotSetup } from "../lib/store/bots.js";
import { storeLLMCall } from "../lib/store/llm-calls.js";
import { getProvider } from "../providers/xai.js";
import type { LLMProvider, LLMMessage } from "../providers/llm.js";

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

const getProviderForBot = (bot: BotSetup): LLMProvider => {
  return getProvider(bot.modelProvider);
};

// ─── Research Agent ──────────────────────────────────────────────────

export const runResearchAgent = async (input: {
  bot: BotSetup;
  systemPrompt: string;
  userMessage: string;
  runId: string | null;
}): Promise<ResearchResult> => {
  const { bot, systemPrompt, userMessage, runId } = input;
  const provider = getProviderForBot(bot);
  const temperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;

  const messages: LLMMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage }
  ];

  let lastError: unknown;

  for (let attempt = 1; attempt <= 2; attempt++) {
    const start = Date.now();
    try {
      const response = await provider.chat({
        model: bot.modelIdentifier,
        messages,
        temperature
      });

      // Log successful call
      if (runId) {
        void storeLLMCall({
          runId,
          phase: "research",
          provider: provider.name,
          model: response.model,
          inputMessages: messages,
          outputText: response.content,
          inputTokens: response.usage?.inputTokens ?? null,
          outputTokens: response.usage?.outputTokens ?? null,
          latencyMs: Date.now() - start,
          attempt,
          strategy: response.strategy,
          error: null
        });
      }

      return {
        rawText: response.content,
        provider: provider.name,
        model: response.model
      };
    } catch (error) {
      lastError = error;
      const errorMessage = error instanceof Error ? error.message : String(error);

      // Log failed call
      if (runId) {
        void storeLLMCall({
          runId,
          phase: "research",
          provider: provider.name,
          model: bot.modelIdentifier,
          inputMessages: messages,
          outputText: null,
          inputTokens: null,
          outputTokens: null,
          latencyMs: Date.now() - start,
          attempt,
          strategy: "text",
          error: errorMessage
        });
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Research request failed");
};

// ─── Trader Agent ────────────────────────────────────────────────────

type ResponseStrategy = {
  label: string;
  format?: Record<string, unknown>;
};

const TRADER_STRATEGIES: ResponseStrategy[] = [
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

export const runTraderAgent = async (input: {
  bot: BotSetup;
  systemPrompt: string;
  userMessage: string;
  runId: string | null;
}): Promise<TraderResult> => {
  const { bot, systemPrompt, userMessage, runId } = input;
  const provider = getProviderForBot(bot);
  const temperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;

  const messages: LLMMessage[] = [
    { role: "system", content: systemPrompt },
    { role: "user", content: userMessage }
  ];

  let lastError: unknown;
  const attemptErrors: string[] = [];

  for (const strategy of TRADER_STRATEGIES) {
    // Try with and without temperature
    for (const useTemp of [true, false]) {
      const start = Date.now();
      const attempt = attemptErrors.length + 1;

      try {
        const response = await provider.chat({
          model: bot.modelIdentifier,
          messages,
          responseFormat: strategy.format,
          temperature: useTemp ? temperature : undefined
        });

        const jsonText = extractJson(response.content);
        let decision: TradingDecision;
        try {
          decision = tradingDecisionSchema.parse(JSON.parse(jsonText));
        } catch (parseError) {
          throw new DecisionParseError(
            `Invalid JSON decision (strategy: ${strategy.label})`,
            response.content,
            { cause: parseError }
          );
        }

        // Log successful call
        if (runId) {
          void storeLLMCall({
            runId,
            phase: "trader",
            provider: provider.name,
            model: response.model,
            inputMessages: messages,
            outputText: response.content,
            inputTokens: response.usage?.inputTokens ?? null,
            outputTokens: response.usage?.outputTokens ?? null,
            latencyMs: Date.now() - start,
            attempt,
            strategy: strategy.label,
            error: null
          });
        }

        return {
          rawText: response.content,
          decision,
          provider: provider.name,
          model: response.model
        };
      } catch (error) {
        lastError = error;
        if (error instanceof DecisionParseError) {
          // Log and rethrow parse errors — they contain the raw text for debugging
          if (runId) {
            void storeLLMCall({
              runId,
              phase: "trader",
              provider: provider.name,
              model: bot.modelIdentifier,
              inputMessages: messages,
              outputText: error.rawText,
              inputTokens: null,
              outputTokens: null,
              latencyMs: Date.now() - start,
              attempt,
              strategy: strategy.label,
              error: error.message
            });
          }
          throw error;
        }

        const errorMessage = error instanceof Error ? error.message : String(error);
        attemptErrors.push(`${strategy.label}/${useTemp ? "temp" : "no-temp"}: ${errorMessage}`);

        // Log failed call
        if (runId) {
          void storeLLMCall({
            runId,
            phase: "trader",
            provider: provider.name,
            model: bot.modelIdentifier,
            inputMessages: messages,
            outputText: null,
            inputTokens: null,
            outputTokens: null,
            latencyMs: Date.now() - start,
            attempt,
            strategy: strategy.label,
            error: errorMessage
          });
        }
      }
    }
  }

  const recentFailures = attemptErrors.slice(-3).join(" | ");
  throw new Error(
    `All trader attempts failed for ${bot.modelIdentifier}. Recent: ${recentFailures}`,
    { cause: lastError }
  );
};

// ─── Symbol Extraction ───────────────────────────────────────────────

export const extractCandidateSymbols = (rawText: string, venueSymbols: string[]): string[] => {
  const venueSet = new Set(venueSymbols.map((s) => s.toUpperCase()));
  const matches = rawText.match(/[A-Z]{2,10}USDT/g);
  if (!matches) return [];
  const unique = new Set<string>();
  for (const m of matches) {
    if (venueSet.has(m) && m !== "USDTUSDT") unique.add(m);
  }
  return Array.from(unique);
};
