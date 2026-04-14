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
  compactContext: Record<string, unknown>;
};

export const requestDecision = async ({
  bot,
  systemPrompt,
  compactContext
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
        content: JSON.stringify(compactContext)
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
