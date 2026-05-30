import { Router, type Router as ExpressRouter } from "express";
import {
  signalDirectionSchema,
  signalSourceKindSchema,
  signalStatusSchema,
  signalUrgencySchema
} from "@cosmu/shared";
import {
  createRawObservation,
  createStandardizedSignal,
  getLatestModelProfile,
  listRawObservations,
  listStandardizedSignals,
  updateStandardizedSignalStatus
} from "../lib/store.js";
import { z } from "zod";
import { getProvider } from "../providers/registry.js";

export const signalsRouter: ExpressRouter = Router();

const signalInputSchema = z.object({
  observationId: z.string().uuid().nullable().optional(),
  asset: z.string().trim().min(1).max(32),
  symbol: z.string().trim().min(2).max(24).nullable().optional(),
  topic: z.string().trim().min(1).max(120),
  direction: signalDirectionSchema.default("neutral"),
  sentimentScore: z.coerce.number().min(-1).max(1).default(0),
  confidence: z.coerce.number().min(0).max(1).default(0.5),
  urgency: signalUrgencySchema.default("medium"),
  horizon: z.string().trim().max(80).nullable().optional(),
  summary: z.string().trim().min(1).max(1200),
  evidenceJson: z.unknown().optional(),
  reasoningSummary: z.string().trim().max(1200).nullable().optional(),
  status: signalStatusSchema.default("new")
});

const observationInputSchema = z.object({
  sourceKind: signalSourceKindSchema.default("manual"),
  sourceName: z.string().trim().min(1).max(120).default("Manual"),
  sourceUrl: z.string().trim().url().nullable().optional(),
  observedAt: z.string().datetime().nullable().optional(),
  title: z.string().trim().min(1).max(240),
  content: z.string().trim().min(1).max(12000),
  rawJson: z.unknown().optional(),
  contentHash: z.string().trim().min(8).max(128).nullable().optional(),
  signal: signalInputSchema.omit({ observationId: true }).optional()
});

const formatterOutputSchema = signalInputSchema
  .omit({ observationId: true, status: true })
  .extend({
    evidenceJson: z.unknown().default([]),
    reasoningSummary: z.string().trim().max(1200).nullable().default(null)
  });

const extractJson = (text: string) => {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) return fenced[1].trim();
  const braceStart = trimmed.indexOf("{");
  if (braceStart > 0) return trimmed.slice(braceStart);
  return trimmed;
};

const formatObservationWithLLM = async (input: z.infer<typeof observationInputSchema>) => {
  const model = await getLatestModelProfile();
  if (!model) throw new Error("Configure a model profile before formatting signals");
  const provider = getProvider(model.provider);
  const response = await provider.chat({
    model: model.model,
    temperature: 0.1,
    responseFormat: { type: "json_object" },
    messages: [
      {
        role: "system",
        content: [
          "You convert raw qualitative market observations into one compact trading signal.",
          "Return exactly one JSON object. No markdown, no prose.",
          "Use this schema:",
          "{",
          "  asset: string, symbol: string|null, topic: string,",
          "  direction: 'bullish'|'bearish'|'neutral'|'mixed',",
          "  sentimentScore: number between -1 and 1,",
          "  confidence: number between 0 and 1,",
          "  urgency: 'low'|'medium'|'high', horizon: string|null,",
          "  summary: string, evidenceJson: array|object, reasoningSummary: string|null",
          "}",
          "Be conservative. Low evidence means low confidence. Do not invent sources."
        ].join("\n")
      },
      {
        role: "user",
        content: [
          `Source kind: ${input.sourceKind}`,
          `Source name: ${input.sourceName}`,
          `Title: ${input.title}`,
          "Observation:",
          input.content
        ].join("\n")
      }
    ]
  });
  return formatterOutputSchema.parse(JSON.parse(extractJson(response.content)));
};

signalsRouter.get("/signals", async (request, response, next) => {
  try {
    const statusRaw = typeof request.query.status === "string" ? request.query.status : undefined;
    const status = statusRaw ? signalStatusSchema.parse(statusRaw) : undefined;
    const asset = typeof request.query.asset === "string" && request.query.asset.trim()
      ? request.query.asset.trim()
      : undefined;
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    response.json({ signals: await listStandardizedSignals({ status, asset, limit }) });
  } catch (error) {
    next(error);
  }
});

signalsRouter.post("/signals", async (request, response, next) => {
  try {
    const input = signalInputSchema.parse(request.body);
    const signal = await createStandardizedSignal(input);
    response.json({ signal });
  } catch (error) {
    next(error);
  }
});

signalsRouter.patch("/signals/:signalId/status", async (request, response, next) => {
  try {
    const body = z.object({ status: signalStatusSchema }).parse(request.body);
    const signal = await updateStandardizedSignalStatus({
      id: request.params.signalId,
      status: body.status
    });
    if (!signal) {
      response.status(404).json({ error: "Signal not found" });
      return;
    }
    response.json({ signal });
  } catch (error) {
    next(error);
  }
});

signalsRouter.get("/signals/observations", async (request, response, next) => {
  try {
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    response.json({ observations: await listRawObservations(limit) });
  } catch (error) {
    next(error);
  }
});

signalsRouter.post("/signals/observations", async (request, response, next) => {
  try {
    const input = observationInputSchema.parse(request.body);
    const observation = await createRawObservation(input);
    const signal = input.signal
      ? await createStandardizedSignal({ ...input.signal, observationId: observation.id })
      : null;
    response.json({ observation, signal });
  } catch (error) {
    next(error);
  }
});

signalsRouter.post("/signals/format", async (request, response, next) => {
  try {
    const input = observationInputSchema.omit({ signal: true }).parse(request.body);
    const observation = await createRawObservation(input);
    const formatted = await formatObservationWithLLM(input);
    const signal = await createStandardizedSignal({ ...formatted, observationId: observation.id });
    response.json({ observation, signal });
  } catch (error) {
    next(error);
  }
});
