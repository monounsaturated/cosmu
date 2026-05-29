// module: Index contracts — scheduled qualitative-to-quantitative signal views.
import { z } from "zod";

export const indexStatusSchema = z.enum(["active", "paused", "error"]);
export const indexRunStatusSchema = z.enum(["running", "success", "failure"]);

export const indexConfigSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  description: z.string().nullable(),
  status: indexStatusSchema,
  cadenceMinutes: z.number().int().positive(),
  sourceKeys: z.array(z.string()),
  promptBody: z.string(),
  outputSchema: z.unknown(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type IndexConfig = z.infer<typeof indexConfigSchema>;

export const indexSnapshotSchema = z.object({
  id: z.string().uuid(),
  indexId: z.string().uuid(),
  value: z.number().nullable(),
  label: z.string().nullable(),
  summary: z.string(),
  evidenceJson: z.unknown(),
  capturedAt: z.string().datetime()
});

export type IndexSnapshot = z.infer<typeof indexSnapshotSchema>;
