// module: Tradability contracts — deterministic bridge from research ideas to executable instruments.
import { z } from "zod";
import { assetClassSchema, venueSchema } from "./venue.js";

export const tradabilityReasonSchema = z.enum([
  "tradable",
  "no_pair",
  "quote_blocked",
  "account_not_allowed",
  "market_closed",
  "venue_not_supported"
]);

export const tradabilityRequestSchema = z.object({
  assetOrSymbol: z.string().trim().min(1).max(64),
  venue: venueSchema,
  assetClass: assetClassSchema.default("spot"),
  sideIntent: z.enum(["buy", "sell", "watch"]).default("watch")
});

export type TradabilityRequest = z.infer<typeof tradabilityRequestSchema>;

export const tradabilityResultSchema = z.object({
  assetOrSymbol: z.string(),
  venue: venueSchema,
  assetClass: assetClassSchema,
  executable: z.boolean(),
  reason: tradabilityReasonSchema,
  symbol: z.string().nullable(),
  instrumentId: z.string().nullable(),
  quoteAsset: z.string().nullable(),
  currentPrice: z.number().nullable(),
  minNotional: z.number().nullable(),
  orderTypes: z.array(z.string()).default([]),
  explanation: z.string(),
  alternatives: z.array(z.object({
    venue: venueSchema,
    symbol: z.string(),
    reason: z.string()
  })).default([])
});

export type TradabilityResult = z.infer<typeof tradabilityResultSchema>;
