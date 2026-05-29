// module: Raw observations + standardized signals (the qualitative-data layer that feeds Indexes).
import { z } from "zod";

export const signalSourceKindSchema = z.enum(["x", "web", "news", "market", "manual"]);
export const signalDirectionSchema = z.enum(["bullish", "bearish", "neutral", "mixed"]);
export const signalUrgencySchema = z.enum(["low", "medium", "high"]);
export const signalStatusSchema = z.enum(["new", "watching", "used", "dismissed"]);

export const rawObservationSchema = z.object({
  id: z.string().uuid(),
  sourceKind: signalSourceKindSchema,
  sourceName: z.string(),
  sourceUrl: z.string().nullable(),
  observedAt: z.string().datetime(),
  capturedAt: z.string().datetime(),
  title: z.string(),
  content: z.string(),
  rawJson: z.unknown().nullable(),
  contentHash: z.string().nullable()
});

export type RawObservation = z.infer<typeof rawObservationSchema>;

export const standardizedSignalSchema = z.object({
  id: z.string().uuid(),
  observationId: z.string().uuid().nullable(),
  asset: z.string(),
  symbol: z.string().nullable(),
  topic: z.string(),
  direction: signalDirectionSchema,
  sentimentScore: z.number().min(-1).max(1),
  confidence: z.number().min(0).max(1),
  urgency: signalUrgencySchema,
  horizon: z.string().nullable(),
  summary: z.string(),
  evidenceJson: z.unknown(),
  reasoningSummary: z.string().nullable(),
  status: signalStatusSchema,
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type StandardizedSignal = z.infer<typeof standardizedSignalSchema>;
