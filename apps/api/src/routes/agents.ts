import { Router, type Router as ExpressRouter } from "express";
import { agentScopeTypeSchema, prePromptConfigSchema, traderConfigSchema } from "@cosmu/shared";
import {
  createBot,
  getAgentControlSummary,
  getApprovalRequest,
  getLatestModelProfile,
  getLatestResearchPromptVersion,
  getResearchCandidate,
  listAgentSteps,
  listApprovalRequests,
  setCandidatePromotedBot,
  updateResearchExperiment,
  updateApprovalStatus
} from "../lib/store.js";

export const agentsRouter: ExpressRouter = Router();

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
    if (approval.requestType === "live_promotion") {
      const payload = approval.payload as { experimentId?: string } | null;
      if (payload?.experimentId) {
        await updateResearchExperiment({ id: payload.experimentId, promotionStatus: "live_rejected" });
      }
    }
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

    let createdBotId: string | null = null;

    if (approval.requestType === "live_promotion") {
      const payload = approval.payload as {
        candidateId?: string;
        experimentId?: string;
        thesis?: string;
      } | null;
      const candidateId = payload?.candidateId;
      if (!candidateId) {
        response.status(400).json({ error: "Approval payload missing candidateId" });
        return;
      }
      const candidate = await getResearchCandidate(candidateId);
      if (!candidate) {
        response.status(404).json({ error: "Linked candidate not found" });
        return;
      }
      if (candidate.promotedBotId) {
        const updated = await updateApprovalStatus({ id: approval.id, status: "approved" });
        response.json({ ok: true, approval: updated, botId: candidate.promotedBotId, alreadyPromoted: true });
        return;
      }
      const prompt = await getLatestResearchPromptVersion();
      const model = await getLatestModelProfile();
      if (!prompt || !model) {
        response.status(409).json({ error: "Configure a research prompt and a model profile before promotion" });
        return;
      }

      createdBotId = await createBot({
        name: candidate.name.replace(/paper candidate$/i, "live").trim(),
        slug: `pro-${candidate.id.slice(0, 8)}`,
        promptVersionId: prompt.versionId,
        modelProfileId: model.id,
        workspaceMode: "pro",
        promptConfig: prePromptConfigSchema.parse({}),
        traderConfig: traderConfigSchema.parse({}),
        runtimeConfig: {
          venue: "binance",
          frequencyMinutes: 60,
          mode: "live",
          assetClass: "spot",
          budgetUsdt: 1000,
          symbolScope: "selected",
          execution: {
            enabled: false,
            allowMarketOrders: true,
            allowLimitOrders: true,
            maxOrdersPerRun: 3,
            maxNotionalPerOrderUsd: 250,
            minCashReserveUsd: 200
          },
          contextSymbols: []
        }
      });

      await setCandidatePromotedBot({ candidateId: candidate.id, botId: createdBotId });
      await updateResearchExperiment({
        id: candidate.experimentId,
        status: "live_candidate",
        promotionStatus: "live_approved"
      });
    } else {
      response.status(400).json({ error: `Approval type ${approval.requestType} is not actionable yet` });
      return;
    }

    const updated = await updateApprovalStatus({ id: approval.id, status: "approved" });
    response.json({ ok: true, approval: updated, botId: createdBotId });
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
