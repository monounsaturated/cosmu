// module: Source contracts — read-only data connectors that create raw observations.
import { z } from "zod";

export const sourceKindSchema = z.enum([
  "manual",
  "market",
  "web",
  "news",
  "social",
  "filing",
  "yahoo_finance",
  "custom_api"
]);

export const sourceCapabilitySchema = z.enum([
  "quote",
  "historical_prices",
  "news",
  "fundamentals",
  "search",
  "documents"
]);

export const sourceDefinitionSchema = z.object({
  key: z.string(),
  label: z.string(),
  kind: sourceKindSchema,
  enabled: z.boolean(),
  capabilities: z.array(sourceCapabilitySchema),
  description: z.string(),
  configHint: z.string().nullable()
});

export type SourceDefinition = z.infer<typeof sourceDefinitionSchema>;

export const sourceFetchRequestSchema = z.object({
  query: z.string().trim().min(1).max(240),
  limit: z.number().int().min(1).max(25).default(5),
  options: z.record(z.string(), z.unknown()).default({})
});

export type SourceFetchRequest = z.infer<typeof sourceFetchRequestSchema>;
