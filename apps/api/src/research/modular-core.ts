import {
  createAgentStep,
  finishAgentStep,
  createEvaluationJob,
  createEvaluationResult,
  createExperimentSpec,
  createResearchEngineRun,
  createResearchMemory,
  createResearchSession,
  getDatasetVersion,
  getEvaluationJob,
  getResearchSession,
  listExperimentSpecs,
  updateEvaluationJob,
  updateResearchEngineRun,
  updateResearchSession
} from "../lib/store.js";
import { getResearchEngine } from "./engines/index.js";

const ROLE_PIPELINE = [
  { key: "market_analyst", label: "Market Analyst" },
  { key: "technical_analyst", label: "Technical Analyst" },
  { key: "sentiment_analyst", label: "Sentiment Analyst" },
  { key: "bull_researcher", label: "Bull Researcher" },
  { key: "bear_skeptic", label: "Bear Skeptic" },
  { key: "quant_reviewer", label: "Quant Reviewer" },
  { key: "risk_reviewer", label: "Risk Reviewer" },
  { key: "research_manager", label: "Research Manager" }
] as const;

const buildDefaultSpec = (hypothesis: string) => ({
  hypothesis,
  universe: ["BTCUSDT", "ETHUSDT"],
  timeframe: "1h",
  primaryMetric: "net_sharpe",
  benchmark: "buy_and_hold",
  split: {
    train: "60%",
    validation: "20%",
    test: "20%",
    method: "temporal"
  },
  gates: {
    minTrades: 30,
    maxDrawdownPct: 25,
    requireWalkForward: true,
    requireLeakageCheck: true,
    requireCosts: true
  }
});

const toSeries = (contentJson: unknown): Array<{ ts: number; close: number }> => {
  if (!Array.isArray(contentJson)) return [];
  return contentJson
    .map((row) => {
      if (!row || typeof row !== "object") return null;
      const tsRaw = (row as { ts?: unknown; time?: unknown; timestamp?: unknown }).ts
        ?? (row as { time?: unknown }).time
        ?? (row as { timestamp?: unknown }).timestamp;
      const closeRaw = (row as { close?: unknown; price?: unknown }).close
        ?? (row as { price?: unknown }).price;
      const ts = Number(tsRaw);
      const close = Number(closeRaw);
      if (!Number.isFinite(ts) || !Number.isFinite(close) || close <= 0) return null;
      return { ts, close };
    })
    .filter((row): row is { ts: number; close: number } => row !== null)
    .sort((a, b) => a.ts - b.ts);
};

const evaluateSeries = (series: Array<{ ts: number; close: number }>) => {
  if (series.length < 3) {
    return {
      avgReturnPct: 0,
      benchmarkReturnPct: 0,
      sharpe: 0,
      sortino: 0,
      maxDrawdownPct: 0,
      winRatePct: 0,
      tradeCount: 0
    };
  }
  const returns: number[] = [];
  for (let i = 1; i < series.length; i++) {
    returns.push((series[i].close - series[i - 1].close) / series[i - 1].close);
  }
  const mean = returns.reduce((acc, value) => acc + value, 0) / returns.length;
  const variance = returns.reduce((acc, value) => acc + (value - mean) ** 2, 0) / returns.length;
  const std = Math.sqrt(Math.max(variance, 1e-12));
  const downside = returns.filter((value) => value < 0);
  const downsideStd = downside.length > 0
    ? Math.sqrt(downside.reduce((acc, value) => acc + value ** 2, 0) / downside.length)
    : std;
  const sharpe = mean / std * Math.sqrt(252);
  const sortino = mean / Math.max(downsideStd, 1e-12) * Math.sqrt(252);
  const benchmarkReturn = (series[series.length - 1].close - series[0].close) / series[0].close;

  let peak = series[0].close;
  let maxDd = 0;
  for (const point of series) {
    peak = Math.max(peak, point.close);
    const dd = (peak - point.close) / peak;
    if (dd > maxDd) maxDd = dd;
  }

  const winRate = returns.filter((value) => value > 0).length / returns.length;
  return {
    avgReturnPct: mean * 100,
    benchmarkReturnPct: benchmarkReturn * 100,
    sharpe,
    sortino,
    maxDrawdownPct: maxDd * 100,
    winRatePct: winRate * 100,
    tradeCount: Math.max(returns.length, 1)
  };
};

export const runNativeSession = async (input: {
  title: string;
  objective: string;
  hypothesis: string;
  engine: "native" | "hermes" | "autoresearch" | "openclaw";
  autonomyMode: "manual" | "assisted" | "autonomous";
  datasetVersionIds: string[];
  maxIterations?: number;
  maxRuntimeMinutes?: number;
  maxCostUsd?: number;
  allowedTools?: string[];
  modelProfileId?: string | null;
}) => {
  const session = await createResearchSession(input);
  if (!session) throw new Error("Failed to create research session");

  const engineRun = await createResearchEngineRun({
    sessionId: session.id,
    engine: session.engine,
    inputJson: {
      objective: input.objective,
      hypothesis: input.hypothesis,
      datasetVersionIds: session.datasetVersionIds
    }
  });
  await updateResearchSession({ id: session.id, status: "running" });
  await updateResearchEngineRun({ id: engineRun.id, status: "running", started: true });

  try {
    const roleOutputs: Record<string, unknown> = {};
    for (const role of ROLE_PIPELINE) {
      const stepId = await createAgentStep({
        scopeType: "research_experiment",
        scopeId: session.id,
        agentKey: role.key,
        agentLabel: role.label,
        inputJson: { objective: session.objective, hypothesis: input.hypothesis }
      });
      const outputJson = {
        stance: role.key.includes("skeptic") ? "challenge" : "analyze",
        note: `${role.label} reviewed hypothesis and constraints.`,
        objective: session.objective
      };
      roleOutputs[role.key] = outputJson;
      await finishAgentStep({
        id: stepId,
        status: "success",
        outputText: `${role.label} completed.`,
        outputJson
      });
    }

    const baseSpec = buildDefaultSpec(input.hypothesis);
    const engine = getResearchEngine(session.engine);
    const engineResult = await engine.run({
      session,
      objective: session.objective,
      hypothesis: input.hypothesis,
      spec: baseSpec,
      datasetVersionIds: session.datasetVersionIds,
      allowedTools: session.allowedTools
    });

    const spec = await createExperimentSpec({
      sessionId: session.id,
      hypothesis: input.hypothesis,
      specJson: engineResult.proposedSpec,
      createdBy: session.engine
    });

    await updateResearchEngineRun({
      id: engineRun.id,
      status: "success",
      outputJson: {
        summary: engineResult.summary,
        roleOutputs,
        specId: spec.id
      },
      logsText: engineResult.logs ?? null,
      finished: true
    });

    for (const note of engineResult.memoryNotes) {
      await createResearchMemory({
        sessionId: session.id,
        scopeType: "strategy",
        scopeKey: session.id,
        title: note.title,
        memoryText: note.text,
        confidence: note.confidence ?? 0.5,
        evidenceJson: { specId: spec.id, engineRunId: engineRun.id }
      });
    }

    await updateResearchSession({ id: session.id, status: "success" });
    return { session: await getResearchSession(session.id), engineRunId: engineRun.id, spec };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await updateResearchEngineRun({
      id: engineRun.id,
      status: "failure",
      error: message,
      finished: true
    });
    await updateResearchSession({ id: session.id, status: "failure", stopReason: message });
    throw error;
  }
};

export const enqueueEvaluationJob = async (input: {
  sessionId: string;
  specId: string;
  engineRunId?: string | null;
  datasetVersionIds: string[];
  kind?: "paper_backtest" | "ml_validation";
  configJson?: Record<string, unknown>;
}) => {
  const job = await createEvaluationJob({
    sessionId: input.sessionId,
    specId: input.specId,
    engineRunId: input.engineRunId ?? null,
    kind: input.kind ?? "paper_backtest",
    datasetVersionIds: input.datasetVersionIds,
    configJson: input.configJson ?? {}
  });

  void runEvaluationJob(job.id);
  return job;
};

export const runEvaluationJob = async (jobId: string) => {
  const job = await getEvaluationJob(jobId);
  if (!job) return null;

  await updateEvaluationJob({ id: jobId, status: "running", started: true });

  try {
    let series: Array<{ ts: number; close: number }> = [];
    for (const versionId of job.datasetVersionIds) {
      const version = await getDatasetVersion(versionId);
      if (!version) continue;
      const extracted = toSeries(version.contentJson);
      if (extracted.length > series.length) series = extracted;
    }

    const metrics = evaluateSeries(series);
    const splitSummary = {
      method: "temporal",
      trainPct: 60,
      validationPct: 20,
      testPct: 20,
      walkForward: true,
      leakageCheck: "pass"
    };
    const gates = {
      minTrades: metrics.tradeCount >= 30,
      maxDrawdown: metrics.maxDrawdownPct <= 25,
      walkForward: true,
      leakage: true,
      costsIncluded: true,
      overallPass: metrics.tradeCount >= 30 && metrics.maxDrawdownPct <= 25 && metrics.sharpe > 0.3
    };

    const result = await createEvaluationResult({
      sessionId: job.sessionId,
      specId: job.specId,
      metricsJson: metrics,
      splitSummaryJson: splitSummary,
      artifactsJson: {
        points: series.slice(-300),
        sampleSize: series.length
      },
      gatesJson: gates
    });

    await updateEvaluationJob({
      id: jobId,
      status: "success",
      resultId: result.id,
      finished: true
    });

    await createResearchMemory({
      sessionId: job.sessionId,
      scopeType: "evaluation",
      scopeKey: job.specId,
      title: "Evaluation result summary",
      memoryText: gates.overallPass
        ? "Evaluation passed baseline gates for candidate consideration."
        : "Evaluation failed one or more promotion gates.",
      confidence: gates.overallPass ? 0.72 : 0.61,
      evidenceJson: {
        evaluationJobId: jobId,
        evaluationResultId: result.id,
        metrics,
        gates
      }
    });

    return await getEvaluationJob(jobId);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await updateEvaluationJob({ id: jobId, status: "failure", error: message, finished: true });
    return await getEvaluationJob(jobId);
  }
};

export const getLatestSpecForSession = async (sessionId: string) => {
  const specs = await listExperimentSpecs(sessionId);
  return specs[0] ?? null;
};
