import { Router, type Router as ExpressRouter } from "express";
import { agentScopeTypeSchema } from "@cosmu/shared";
import {
  getAgentControlSummary,
  getApprovalRequest,
  listAgentSteps,
  listApprovalRequests,
  updateApprovalStatus
} from "../lib/store.js";
import { listAgentDefinitions } from "../services/agent-registry.js";

export const agentsRouter: ExpressRouter = Router();

agentsRouter.get("/agents/registry", async (_request, response) => {
  response.json({ agents: listAgentDefinitions() });
});

agentsRouter.get("/agent-control/summary", async (_request, response, next) => {
  try {
    response.json(await getAgentControlSummary());
  } catch (error) {
    next(error);
  }
});

agentsRouter.get("/agent-control/approvals", async (request, response, next) => {
  try {
    const status = typeof request.query.status === "string" ? request.query.status : undefined;
    const allowed = ["pending", "approved", "rejected", "cancelled"] as const;
    const filter = allowed.includes(status as (typeof allowed)[number])
      ? { status: status as (typeof allowed)[number] }
      : undefined;
    response.json({ approvals: await listApprovalRequests(filter) });
  } catch (error) {
    next(error);
  }
});

agentsRouter.post("/agent-control/approvals/:approvalId/reject", async (request, response, next) => {
  try {
    const approval = await getApprovalRequest(request.params.approvalId);
    if (!approval) {
      response.status(404).json({ error: "Approval not found" });
      return;
    }
    if (approval.status !== "pending") {
      response.status(409).json({ error: `Approval is already ${approval.status}` });
      return;
    }
    const updated = await updateApprovalStatus({ id: approval.id, status: "rejected" });
    response.json({ ok: true, approval: updated });
  } catch (error) {
    next(error);
  }
});

agentsRouter.post("/agent-control/approvals/:approvalId/approve", async (request, response, next) => {
  try {
    const approval = await getApprovalRequest(request.params.approvalId);
    if (!approval) {
      response.status(404).json({ error: "Approval not found" });
      return;
    }
    if (approval.status !== "pending") {
      response.status(409).json({ error: `Approval is already ${approval.status}` });
      return;
    }

    const updated = await updateApprovalStatus({ id: approval.id, status: "approved" });
    response.json({ ok: true, approval: updated });
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
