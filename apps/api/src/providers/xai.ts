import OpenAI from "openai";
import { tradingDecisionJsonSchema, tradingDecisionSchema, type TradingDecision } from "@cosmu/shared";
import { env } from "../env.js";
import type { BotSetup } from "../lib/store.js";

const client = new OpenAI({
  apiKey: env.XAI_API_KEY,
  baseURL: "https://api.x.ai/v1"
});

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
  {
    label: "json_object",
    format: { type: "json_object" }
  },
  {
    label: "text"
  }
];

const TEMPERATURE_STRATEGIES: TemperatureStrategy[] = [
  { label: "with_temperature", includeTemperature: true },
  { label: "without_temperature", includeTemperature: false }
];

export const requestDecision = async ({
  bot,
  systemPrompt,
  userMessage
}: DecisionRequest): Promise<{ rawText: string; decision: TradingDecision }> => {
  let lastError: unknown;
  const configuredTemperature =
    typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined;

  for (const strategy of STRATEGIES) {
    for (const tempStrategy of TEMPERATURE_STRATEGIES) {
      try {
        const completion = await client.chat.completions.create({
          model: bot.modelIdentifier,
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
            `xAI returned no content (strategy: ${strategy.label}, temperature: ${tempStrategy.label})`
          );
        }

        const jsonText = extractJson(rawText);
        let decision: TradingDecision;
        try {
          decision = tradingDecisionSchema.parse(JSON.parse(jsonText));
        } catch (parseError) {
          throw new DecisionParseError(
            `xAI returned invalid JSON decision (strategy: ${strategy.label}, temperature: ${tempStrategy.label})`,
            rawText,
            { cause: parseError }
          );
        }

        return { rawText, decision };
      } catch (error) {
        lastError = error;
        if (error instanceof DecisionParseError) throw error;
        console.warn(
          `Decision strategy "${strategy.label}" (${tempStrategy.label}) failed: ${String(error)}`
        );
      }
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("All decision strategies failed");
};

export const listXaiModels = async () => {
  const response = await fetch("https://api.x.ai/v1/models", {
    headers: {
      Authorization: `Bearer ${env.XAI_API_KEY}`
    },
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
    .filter((row: { id: string; created: number | null }) => row.id.length > 0);
};
