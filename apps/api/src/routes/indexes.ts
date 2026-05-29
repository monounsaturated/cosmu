// module: Index routes — configure and inspect signal-derived indexes.
import { Router, type Router as ExpressRouter } from "express";
import { z } from "zod";
import { createIndexConfig, listIndexConfigs, listIndexSnapshots } from "../lib/store.js";

export const indexesRouter: ExpressRouter = Router();

const slugify = (value: string) =>
  value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

const createIndexSchema = z.object({
  name: z.string().trim().min(1).max(120),
  slug: z.string().trim().min(1).max(140).optional(),
  description: z.string().trim().max(1000).nullable().optional(),
  cadenceMinutes: z.coerce.number().int().positive().max(10080).default(60),
  sourceKeys: z.array(z.string().trim().min(1)).max(20).default([]),
  promptBody: z.string().trim().min(1).max(12000),
  outputSchema: z.unknown().optional()
});

indexesRouter.get("/indexes", async (_request, response, next) => {
  try {
    response.json({ indexes: await listIndexConfigs() });
  } catch (error) {
    next(error);
  }
});

indexesRouter.post("/indexes", async (request, response, next) => {
  try {
    const input = createIndexSchema.parse(request.body);
    const index = await createIndexConfig({
      ...input,
      slug: input.slug ? slugify(input.slug) : `${slugify(input.name)}-${Date.now().toString(36)}`
    });
    response.json({ index });
  } catch (error) {
    next(error);
  }
});

indexesRouter.get("/indexes/:indexId/snapshots", async (request, response, next) => {
  try {
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    response.json({ snapshots: await listIndexSnapshots(request.params.indexId, limit) });
  } catch (error) {
    next(error);
  }
});
