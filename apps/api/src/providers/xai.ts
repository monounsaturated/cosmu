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

export const requestDecision = async ({
  bot,
  systemPrompt,
  userMessage
}: DecisionRequest): Promise<{ rawText: string; decision: TradingDecision }> => {
  const completion = await client.chat.completions.create({
    model: bot.modelIdentifier,
    temperature:
      typeof bot.modelSettings.temperature === "number" ? bot.modelSettings.temperature : undefined,
    messages: [
      {
        role: "system",
        content: systemPrompt
      },
      {
        role: "user",
        content: userMessage
      }
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "TradingDecision",
        schema: tradingDecisionJsonSchema,
        strict: true
      }
    }
  });

  const rawText = completion.choices[0]?.message?.content;

  if (!rawText) {
    throw new Error("xAI returned no structured decision content");
  }

  return {
    rawText,
    decision: tradingDecisionSchema.parse(JSON.parse(rawText))
  };
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
