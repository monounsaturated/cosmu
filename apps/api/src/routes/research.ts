import { Router, type Router as ExpressRouter } from "express";
import { dataSourceKindSchema, prePromptConfigSchema, traderConfigSchema } from "@cosmu/shared";
import {
  createApprovalRequest,
  createBot,
  createResearchDataSource,
  createResearchExperiment,
  getLatestModelProfile,
  getLatestResearchPromptVersion,
  getResearchCandidate,
  getResearchExperiment,
  listAgentSteps,
  listResearchCandidates,
  listResearchDataSources,
  listResearchExperiments,
  setCandidatePaperBot
} from "../lib/store.js";
import { runResearchExperiment } from "../research/orchestrator.js";

export const researchRouter: ExpressRouter = Router();

const titleFromHypothesis = (hypothesis: string) => {
  const trimmed = hypothesis.trim().replace(/\s+/g, " ");
  return trimmed.length > 72 ? `${trimmed.slice(0, 69)}...` : trimmed;
};

researchRouter.get("/research/experiments", async (_request, response, next) => {
  try {
    response.json({ experiments: await listResearchExperiments() });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/experiments", async (request, response, next) => {
  try {
    const body = request.body as { title?: unknown; hypothesis?: unknown; run?: unknown };
    if (typeof body.hypothesis !== "string" || body.hypothesis.trim().length < 5) {
      response.status(400).json({ error: "hypothesis is required" });
      return;
    }

    const hypothesis = body.hypothesis.trim();
    const title = typeof body.title === "string" && body.title.trim().length > 0
      ? body.title.trim()
      : titleFromHypothesis(hypothesis);
    const experiment = await createResearchExperiment({ title, hypothesis });

    if (body.run === false) {
      response.json({ experiment, ran: false });
      return;
    }

    const result = await runResearchExperiment(experiment.id);
    const steps = await listAgentSteps({ scopeType: "research_experiment", scopeId: experiment.id });
    response.json({ ...result, steps, ran: true });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/experiments/:experimentId", async (request, response, next) => {
  try {
    const experiment = await getResearchExperiment(request.params.experimentId);
    if (!experiment) {
      response.status(404).json({ error: "Experiment not found" });
      return;
    }
    const steps = await listAgentSteps({
      scopeType: "research_experiment",
      scopeId: request.params.experimentId
    });
    response.json({ experiment, steps });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/experiments/:experimentId/run", async (request, response, next) => {
  try {
    const result = await runResearchExperiment(request.params.experimentId);
    const steps = await listAgentSteps({
      scopeType: "research_experiment",
      scopeId: request.params.experimentId
    });
    response.json({ ...result, steps });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/data-sources", async (_request, response, next) => {
  try {
    response.json({ dataSources: await listResearchDataSources() });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/data-sources", async (request, response, next) => {
  try {
    const body = request.body as { name?: unknown; kind?: unknown; enabled?: unknown; config?: unknown };
    if (typeof body.name !== "string" || body.name.trim().length === 0) {
      response.status(400).json({ error: "name is required" });
      return;
    }
    const kind = dataSourceKindSchema.parse(body.kind);
    const dataSource = await createResearchDataSource({
      name: body.name.trim(),
      kind,
      enabled: typeof body.enabled === "boolean" ? body.enabled : true,
      config: body.config ?? {}
    });
    response.json({ dataSource });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/candidates", async (_request, response, next) => {
  try {
    response.json({ candidates: await listResearchCandidates() });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/candidates/:candidateId/paper-bot", async (request, response, next) => {
  try {
    const candidate = await getResearchCandidate(request.params.candidateId);
    if (!candidate) {
      response.status(404).json({ error: "Candidate not found" });
      return;
    }
    const existingPaperBotId = (candidate.metrics as { paperBotId?: string } | null)?.paperBotId;
    if (existingPaperBotId) {
      response.status(409).json({ error: "Paper bot already exists for this candidate", botId: existingPaperBotId });
      return;
    }

    const prompt = await getLatestResearchPromptVersion();
    const model = await getLatestModelProfile();
    if (!prompt || !model) {
      response.status(409).json({ error: "Configure a research prompt and a model profile before creating bots" });
      return;
    }

    const botSlug = `research-${candidate.id.slice(0, 8)}`;
    const botId = await createBot({
      name: candidate.name,
      slug: botSlug,
      promptVersionId: prompt.versionId,
      modelProfileId: model.id,
      workspaceMode: "research",
      promptConfig: prePromptConfigSchema.parse({}),
      traderConfig: traderConfigSchema.parse({}),
      runtimeConfig: {
        venue: "binance-testnet",
        frequencyMinutes: 60,
        mode: "testnet",
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

    await setCandidatePaperBot({ candidateId: candidate.id, botId });
    response.json({ ok: true, botId });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/candidates/:candidateId/promote-to-pro", async (request, response, next) => {
  try {
    const candidate = await getResearchCandidate(request.params.candidateId);
    if (!candidate) {
      response.status(404).json({ error: "Candidate not found" });
      return;
    }

    const approval = await createApprovalRequest({
      requestType: "live_promotion",
      title: `Promote "${candidate.name}" to Cosmu Pro`,
      body: candidate.thesis,
      payload: {
        candidateId: candidate.id,
        experimentId: candidate.experimentId,
        thesis: candidate.thesis,
        riskNotes: candidate.riskNotes,
        metrics: candidate.metrics,
        suggestedMode: "live",
        suggestedVenue: "binance"
      }
    });

    response.json({ ok: true, approval });
  } catch (error) {
    next(error);
  }
});
