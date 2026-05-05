import { Router, type Router as ExpressRouter } from "express";
import { agentScopeTypeSchema } from "@cosmu/shared";
import { getAgentControlSummary, listAgentSteps } from "../lib/store.js";

export const agentsRouter: ExpressRouter = Router();

agentsRouter.get("/agent-control/summary", async (_request, response, next) => {
  try {
    response.json(await getAgentControlSummary());
  } catch (error) {
    next(error);
  }
});

agentsRouter.get("/agent-steps", async (request, response, next) => {
  try {
    const scopeTypeRaw = typeof request.query.scopeType === "string" ? request.query.scopeType : undefined;
    const scopeType = scopeTypeRaw ? agentScopeTypeSchema.parse(scopeTypeRaw) : undefined;
    const scopeId = typeof request.query.scopeId === "string" ? request.query.scopeId : undefined;
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    const steps = await listAgentSteps({ scopeType, scopeId, limit });
    response.json({ steps });
  } catch (error) {
    next(error);
  }
});
