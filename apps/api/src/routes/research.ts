import { Router, type Router as ExpressRouter } from "express";
import {
  dataSourceKindSchema,
  evaluationKindSchema,
  prePromptConfigSchema,
  researchAutonomyModeSchema,
  researchEngineSchema,
  traderConfigSchema
} from "@cosmu/shared";
import {
  createBot,
  createResearchDataSource,
  createResearchExperiment,
  getLatestModelProfile,
  getLatestResearchPromptVersion,
  getResearchCandidate,
  getResearchExperiment,
  getResearchSession,
  getEvaluationJob,
  listAgentSteps,
  listResearchCandidates,
  listResearchDataSources,
  listResearchExperiments,
  listDatasets,
  createDataset,
  createDatasetVersion,
  listDatasetVersions,
  listResearchSessions,
  listResearchEngineRuns,
  listExperimentSpecs,
  getExperimentSpec,
  updateExperimentSpec,
  listEvaluationJobs,
  listResearchMemories,
  updateResearchMemory,
  setCandidateVenueBot,
  updateResearchExperiment,
  updateResearchDataSource
} from "../lib/store.js";
import { runResearchExperiment } from "../research/orchestrator.js";
import {
  enqueueEvaluationJob,
  getLatestSpecForSession,
  runNativeSession,
  runEvaluationJob
} from "../research/modular-core.js";

export const researchRouter: ExpressRouter = Router();

const titleFromHypothesis = (hypothesis: string) => {
  const trimmed = hypothesis.trim().replace(/\s+/g, " ");
  return trimmed.length > 72 ? `${trimmed.slice(0, 69)}...` : trimmed;
};

researchRouter.get("/research/page-data", async (_request, response, next) => {
  try {
    const experiments = await listResearchExperiments();
    const dataSources = await listResearchDataSources();
    const candidates = await listResearchCandidates();
    const datasets = await listDatasets();
    const sessions = await listResearchSessions();
    const memories = await listResearchMemories();
    response.json({ experiments, dataSources, candidates, datasets, sessions, memories });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/experiments", async (_request, response, next) => {
  try {
    response.json({ experiments: await listResearchExperiments() });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/datasets", async (_request, response, next) => {
  try {
    response.json({ datasets: await listDatasets() });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/datasets", async (request, response, next) => {
  try {
    const body = request.body as {
      name?: unknown;
      sourceKind?: unknown;
      description?: unknown;
      tags?: unknown;
      version?: unknown;
    };
    if (typeof body.name !== "string" || body.name.trim().length < 2) {
      response.status(400).json({ error: "name is required" });
      return;
    }
    const sourceKind = typeof body.sourceKind === "string"
      && ["upload", "binance_ohlcv", "external_api", "manual"].includes(body.sourceKind)
      ? body.sourceKind as "upload" | "binance_ohlcv" | "external_api" | "manual"
      : "manual";
    const tags = Array.isArray(body.tags) ? body.tags.map((item) => String(item)) : [];
    const dataset = await createDataset({
      name: body.name.trim(),
      sourceKind,
      description: typeof body.description === "string" ? body.description : null,
      tags
    });

    let version = null;
    if (body.version && typeof body.version === "object") {
      const payload = body.version as {
        schemaJson?: unknown;
        metadataJson?: unknown;
        rowCount?: unknown;
        startAt?: unknown;
        endAt?: unknown;
        contentJson?: unknown;
        contentHash?: unknown;
      };
      version = await createDatasetVersion({
        datasetId: dataset.id,
        schemaJson: payload.schemaJson ?? {},
        metadataJson: payload.metadataJson ?? {},
        rowCount: typeof payload.rowCount === "number" ? payload.rowCount : null,
        startAt: typeof payload.startAt === "string" ? payload.startAt : null,
        endAt: typeof payload.endAt === "string" ? payload.endAt : null,
        contentJson: payload.contentJson ?? null,
        contentHash: typeof payload.contentHash === "string" ? payload.contentHash : null
      });
    }

    response.json({ dataset, version });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/datasets/:datasetId/versions", async (request, response, next) => {
  try {
    response.json({ versions: await listDatasetVersions(request.params.datasetId) });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/datasets/:datasetId/versions", async (request, response, next) => {
  try {
    const body = request.body as {
      schemaJson?: unknown;
      metadataJson?: unknown;
      rowCount?: unknown;
      startAt?: unknown;
      endAt?: unknown;
      contentJson?: unknown;
      contentHash?: unknown;
    };
    const version = await createDatasetVersion({
      datasetId: request.params.datasetId,
      schemaJson: body.schemaJson ?? {},
      metadataJson: body.metadataJson ?? {},
      rowCount: typeof body.rowCount === "number" ? body.rowCount : null,
      startAt: typeof body.startAt === "string" ? body.startAt : null,
      endAt: typeof body.endAt === "string" ? body.endAt : null,
      contentJson: body.contentJson ?? null,
      contentHash: typeof body.contentHash === "string" ? body.contentHash : null
    });
    response.json({ version });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/sessions", async (_request, response, next) => {
  try {
    response.json({ sessions: await listResearchSessions() });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/sessions", async (request, response, next) => {
  try {
    const body = request.body as {
      title?: unknown;
      objective?: unknown;
      hypothesis?: unknown;
      engine?: unknown;
      autonomyMode?: unknown;
      datasetVersionIds?: unknown;
      maxIterations?: unknown;
      maxRuntimeMinutes?: unknown;
      maxCostUsd?: unknown;
      allowedTools?: unknown;
      modelProfileId?: unknown;
    };
    const objective = typeof body.objective === "string" ? body.objective.trim() : "";
    const hypothesis = typeof body.hypothesis === "string" ? body.hypothesis.trim() : objective;
    if (objective.length < 5) {
      response.status(400).json({ error: "objective is required" });
      return;
    }
    const title = typeof body.title === "string" && body.title.trim().length > 0
      ? body.title.trim()
      : titleFromHypothesis(objective);
    const engine = researchEngineSchema.parse(typeof body.engine === "string" ? body.engine : "native");
    const autonomyMode = researchAutonomyModeSchema.parse(
      typeof body.autonomyMode === "string" ? body.autonomyMode : "assisted"
    );
    const datasetVersionIds = Array.isArray(body.datasetVersionIds)
      ? body.datasetVersionIds.map((id) => String(id))
      : [];
    const allowedTools = Array.isArray(body.allowedTools)
      ? body.allowedTools.map((tool) => String(tool))
      : [];

    const result = await runNativeSession({
      title,
      objective,
      hypothesis,
      engine,
      autonomyMode,
      datasetVersionIds,
      maxIterations: typeof body.maxIterations === "number" ? body.maxIterations : undefined,
      maxRuntimeMinutes: typeof body.maxRuntimeMinutes === "number" ? body.maxRuntimeMinutes : undefined,
      maxCostUsd: typeof body.maxCostUsd === "number" ? body.maxCostUsd : undefined,
      allowedTools,
      modelProfileId: typeof body.modelProfileId === "string" ? body.modelProfileId : null
    });

    response.json(result);
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/sessions/:sessionId", async (request, response, next) => {
  try {
    const session = await getResearchSession(request.params.sessionId);
    if (!session) {
      response.status(404).json({ error: "Session not found" });
      return;
    }
    const [engineRuns, specs, evaluations, memories, steps] = await Promise.all([
      listResearchEngineRuns(session.id),
      listExperimentSpecs(session.id),
      listEvaluationJobs(session.id),
      listResearchMemories(session.id),
      listAgentSteps({ scopeType: "research", scopeId: session.id })
    ]);
    response.json({ session, engineRuns, specs, evaluations, memories, steps });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/sessions/:sessionId/run-engine", async (request, response, next) => {
  try {
    const session = await getResearchSession(request.params.sessionId);
    if (!session) {
      response.status(404).json({ error: "Session not found" });
      return;
    }
    const latestSpec = await getLatestSpecForSession(session.id);
    response.json({
      ok: true,
      session,
      message: "Session engines run at creation in v1. Re-run pipeline will be added in next step.",
      latestSpec
    });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/engine-runs/:runId", async (request, response, next) => {
  try {
    const sessionId = typeof request.query.sessionId === "string" ? request.query.sessionId : null;
    if (!sessionId) {
      response.status(400).json({ error: "sessionId query is required" });
      return;
    }
    const runs = await listResearchEngineRuns(sessionId);
    const run = runs.find((item) => item.id === request.params.runId) ?? null;
    if (!run) {
      response.status(404).json({ error: "Engine run not found for this session" });
      return;
    }
    response.json({ run });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/specs/:specId", async (request, response, next) => {
  try {
    const spec = await getExperimentSpec(request.params.specId);
    if (!spec) {
      response.status(404).json({ error: "Spec not found" });
      return;
    }
    response.json({ spec });
  } catch (error) {
    next(error);
  }
});

researchRouter.patch("/research/specs/:specId", async (request, response, next) => {
  try {
    const body = request.body as { specJson?: unknown; status?: unknown };
    const status = typeof body.status === "string"
      && ["draft", "locked", "superseded"].includes(body.status)
      ? body.status as "draft" | "locked" | "superseded"
      : undefined;
    const spec = await updateExperimentSpec({
      id: request.params.specId,
      specJson: body.specJson,
      status
    });
    if (!spec) {
      response.status(404).json({ error: "Spec not found" });
      return;
    }
    response.json({ spec });
  } catch (error) {
    next(error);
  }
});

researchRouter.post("/research/evaluations", async (request, response, next) => {
  try {
    const body = request.body as {
      sessionId?: unknown;
      specId?: unknown;
      engineRunId?: unknown;
      datasetVersionIds?: unknown;
      kind?: unknown;
      configJson?: unknown;
      runNow?: unknown;
    };
    if (typeof body.sessionId !== "string" || typeof body.specId !== "string") {
      response.status(400).json({ error: "sessionId and specId are required" });
      return;
    }
    const kind = evaluationKindSchema.parse(typeof body.kind === "string" ? body.kind : "backtest");
    const datasetVersionIds = Array.isArray(body.datasetVersionIds)
      ? body.datasetVersionIds.map((id) => String(id))
      : [];
    const job = await enqueueEvaluationJob({
      sessionId: body.sessionId,
      specId: body.specId,
      engineRunId: typeof body.engineRunId === "string" ? body.engineRunId : null,
      datasetVersionIds,
      kind,
      configJson: typeof body.configJson === "object" && body.configJson ? body.configJson as Record<string, unknown> : {}
    });
    if (body.runNow === true) {
      await runEvaluationJob(job.id);
    }
    response.json({ job: await getEvaluationJob(job.id) });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/evaluations/:jobId", async (request, response, next) => {
  try {
    const job = await getEvaluationJob(request.params.jobId);
    if (!job) {
      response.status(404).json({ error: "Evaluation job not found" });
      return;
    }
    response.json({ job });
  } catch (error) {
    next(error);
  }
});

researchRouter.get("/research/memory", async (request, response, next) => {
  try {
    const sessionId = typeof request.query.sessionId === "string" ? request.query.sessionId : undefined;
    response.json({ memories: await listResearchMemories(sessionId) });
  } catch (error) {
    next(error);
  }
});

researchRouter.patch("/research/memory/:memoryId", async (request, response, next) => {
  try {
    const body = request.body as { active?: unknown; memoryText?: unknown; confidence?: unknown };
    const memory = await updateResearchMemory({
      id: request.params.memoryId,
      active: typeof body.active === "boolean" ? body.active : undefined,
      memoryText: typeof body.memoryText === "string" ? body.memoryText : undefined,
      confidence: typeof body.confidence === "number" ? body.confidence : undefined
    });
    if (!memory) {
      response.status(404).json({ error: "Memory not found" });
      return;
    }
    response.json({ memory });
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
    const steps = await listAgentSteps({ scopeType: "research", scopeId: experiment.id });
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
      scopeType: "research",
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
      scopeType: "research",
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

researchRouter.patch("/research/data-sources/:sourceId", async (request, response, next) => {
  try {
    const body = request.body as { name?: unknown; kind?: unknown; enabled?: unknown; config?: unknown };
    const input = {
      id: request.params.sourceId,
      name: typeof body.name === "string" && body.name.trim() ? body.name.trim() : undefined,
      kind: body.kind === undefined ? undefined : dataSourceKindSchema.parse(body.kind),
      enabled: typeof body.enabled === "boolean" ? body.enabled : undefined,
      config: body.config
    };
    const dataSource = await updateResearchDataSource(input);
    if (!dataSource) {
      response.status(404).json({ error: "Data source not found" });
      return;
    }
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

const createCandidateVenueBot = async (candidateId: string) => {
  const candidate = await getResearchCandidate(candidateId);
  if (!candidate) {
    return { status: 404, body: { error: "Candidate not found" } };
  }
  const existingBotId = (candidate.metrics as { venueBotId?: string } | null)?.venueBotId
    ?? candidate.botId;
  if (existingBotId) {
    return { status: 409, body: { error: "Research bot already exists for this candidate", botId: existingBotId } };
  }

  const prompt = await getLatestResearchPromptVersion();
  const model = await getLatestModelProfile();
  if (!prompt || !model) {
    return { status: 409, body: { error: "Configure a research prompt and a model profile before creating bots" } };
  }

  const venue = "binance-testnet" as const;
  const botSlug = `research-${candidate.id.slice(0, 8)}`;
  const botId = await createBot({
    name: candidate.name,
    slug: botSlug,
    promptVersionId: prompt.versionId,
    modelProfileId: model.id,
    promptConfig: prePromptConfigSchema.parse({}),
    traderConfig: traderConfigSchema.parse({}),
    runtimeConfig: {
      venue,
      frequencyMinutes: 60,
      assetClass: "spot",
      budgetUsdt: 1000,
      symbolScope: "selected",
      execution: {
        enabled: false,
        maxDrawdownEnabled: false,
        allowMarketOrders: true,
        allowLimitOrders: true,
        maxOrdersPerRun: 3,
        maxNotionalPerOrderUsd: 250,
        minCashReserveUsd: 200,
        maxDrawdownPct: 10
      },
      contextSymbols: []
    }
  });

  await setCandidateVenueBot({ candidateId: candidate.id, botId, venue });
  await updateResearchExperiment({ id: candidate.experimentId, progressStatus: "bot_created" });
  return { status: 200, body: { ok: true, botId, venue } };
};

researchRouter.post("/research/candidates/:candidateId/venue-bot", async (request, response, next) => {
  try {
    const result = await createCandidateVenueBot(request.params.candidateId);
    response.status(result.status).json(result.body);
  } catch (error) {
    next(error);
  }
});
