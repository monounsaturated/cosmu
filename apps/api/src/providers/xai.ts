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
      } catch {
        details.push("payload=[unserializable]");
      }
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
    .filter((row: { id: string; created: number | null }) => isLikelyChatModel(row.id));
};
