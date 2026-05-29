// module: Tradability routes — deterministic resolver for agent research ideas.
import { Router, type Router as ExpressRouter } from "express";
import { z } from "zod";
import { resolveTradability, resolveTradabilityBatch } from "../services/tradability.js";

export const tradabilityRouter: ExpressRouter = Router();

tradabilityRouter.post("/tradability/resolve", async (request, response, next) => {
  try {
    response.json({ result: await resolveTradability(request.body) });
  } catch (error) {
    next(error);
  }
});

tradabilityRouter.post("/tradability/resolve-batch", async (request, response, next) => {
  try {
    const body = z.object({ items: z.array(z.unknown()).min(1).max(25) }).parse(request.body);
    response.json({ results: await resolveTradabilityBatch(body.items) });
  } catch (error) {
    next(error);
  }
});
