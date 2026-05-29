// module: Research domain — experiments, candidates, datasets, sessions, engine runs, evaluations, memory.
import { z } from "zod";

export const researchExperimentStatusSchema = z.enum([
  "draft",
  "running",
  "rejected",
  "paper_candidate",
  "live_candidate"
]);
export const promotionStatusSchema = z.enum([
  "none",
  "paper_auto",
  "live_pending_approval",
  "live_approved",
  "live_rejected"
]);
export const dataSourceKindSchema = z.enum([
  "market",
  "news",
  "web",
  "social",
  "weather",
  "astro",
  "tradingview",
  "csv",
  "custom_api",
  "ibkr",
  "polymarket"
]);

export const researchEngineSchema = z.enum(["native", "hermes", "autoresearch", "openclaw"]);
export type ResearchEngine = z.infer<typeof researchEngineSchema>;
export const researchAutonomyModeSchema = z.enum(["manual", "assisted", "autonomous"]);
export const researchSessionStatusSchema = z.enum(["draft", "queued", "running", "success", "failure", "stopped"]);
export const engineRunStatusSchema = z.enum(["queued", "running", "success", "failure", "cancelled"]);
export const evaluationJobStatusSchema = z.enum(["queued", "running", "success", "failure", "cancelled"]);
export const evaluationKindSchema = z.enum(["backtest", "ml_validation"]);

export const researchDataSourceSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  kind: dataSourceKindSchema,
  enabled: z.boolean(),
  config: z.unknown(),
  healthStatus: z.enum(["unknown", "ok", "warning", "error"]),
  lastCheckedAt: z.string().datetime().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type ResearchDataSource = z.infer<typeof researchDataSourceSchema>;

export const researchExperimentSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  hypothesis: z.string(),
  status: researchExperimentStatusSchema,
  promotionStatus: promotionStatusSchema,
  planJson: z.unknown().nullable(),
  resultJson: z.unknown().nullable(),
  skepticVerdict: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type ResearchExperiment = z.infer<typeof researchExperimentSchema>;

export const researchCandidateSchema = z.object({
  id: z.string().uuid(),
  experimentId: z.string().uuid(),
  name: z.string(),
  status: z.enum(["paper_ready", "paper_running", "paper_rejected", "live_candidate"]),
  thesis: z.string(),
  metrics: z.unknown().nullable(),
  riskNotes: z.string().nullable(),
  promotedBotId: z.string().uuid().nullable().default(null),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type ResearchCandidate = z.infer<typeof researchCandidateSchema>;

export const datasetSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  sourceKind: z.enum(["upload", "binance_ohlcv", "external_api", "manual"]),
  description: z.string().nullable(),
  tags: z.array(z.string()),
  active: z.boolean(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type Dataset = z.infer<typeof datasetSchema>;

export const datasetVersionSchema = z.object({
  id: z.string().uuid(),
  datasetId: z.string().uuid(),
  versionNumber: z.number().int().positive(),
  schemaJson: z.unknown(),
  metadataJson: z.unknown(),
  rowCount: z.number().int().nullable(),
  startAt: z.string().datetime().nullable(),
  endAt: z.string().datetime().nullable(),
  contentHash: z.string().nullable(),
  createdAt: z.string().datetime()
});

export type DatasetVersion = z.infer<typeof datasetVersionSchema>;

export const researchSessionSchema = z.object({
  id: z.string().uuid(),
  title: z.string(),
  objective: z.string(),
  engine: researchEngineSchema,
  autonomyMode: researchAutonomyModeSchema,
  status: researchSessionStatusSchema,
  modelProfileId: z.string().uuid().nullable(),
  maxIterations: z.number().int().positive(),
  maxRuntimeMinutes: z.number().int().positive(),
  maxCostUsd: z.number(),
  allowedTools: z.array(z.string()),
  stopReason: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  datasetVersionIds: z.array(z.string().uuid()).default([])
});

export type ResearchSession = z.infer<typeof researchSessionSchema>;

export const researchEngineRunSchema = z.object({
  id: z.string().uuid(),
  sessionId: z.string().uuid(),
  engine: researchEngineSchema,
  status: engineRunStatusSchema,
  inputJson: z.unknown(),
  outputJson: z.unknown().nullable(),
  logsText: z.string().nullable(),
  error: z.string().nullable(),
  startedAt: z.string().datetime().nullable(),
  finishedAt: z.string().datetime().nullable(),
  createdAt: z.string().datetime()
});

export type ResearchEngineRun = z.infer<typeof researchEngineRunSchema>;

export const experimentSpecSchema = z.object({
  id: z.string().uuid(),
  sessionId: z.string().uuid(),
  versionNumber: z.number().int().positive(),
  hypothesis: z.string(),
  specJson: z.unknown(),
  status: z.enum(["draft", "locked", "superseded"]),
  createdBy: z.string(),
  createdAt: z.string().datetime()
});

export type ExperimentSpec = z.infer<typeof experimentSpecSchema>;

export const evaluationResultSchema = z.object({
  id: z.string().uuid(),
  sessionId: z.string().uuid(),
  specId: z.string().uuid(),
  metricsJson: z.unknown(),
  splitSummaryJson: z.unknown(),
  artifactsJson: z.unknown(),
  gatesJson: z.unknown(),
  createdAt: z.string().datetime()
});

export type EvaluationResult = z.infer<typeof evaluationResultSchema>;

export const evaluationJobSchema = z.object({
  id: z.string().uuid(),
  sessionId: z.string().uuid(),
  specId: z.string().uuid(),
  engineRunId: z.string().uuid().nullable(),
  status: evaluationJobStatusSchema,
  kind: evaluationKindSchema,
  datasetVersionIds: z.array(z.string().uuid()),
  configJson: z.unknown(),
  resultId: z.string().uuid().nullable(),
  error: z.string().nullable(),
  startedAt: z.string().datetime().nullable(),
  finishedAt: z.string().datetime().nullable(),
  createdAt: z.string().datetime(),
  result: evaluationResultSchema.nullable().optional()
});

export type EvaluationJob = z.infer<typeof evaluationJobSchema>;

export const researchMemorySchema = z.object({
  id: z.string().uuid(),
  sessionId: z.string().uuid().nullable(),
  scopeType: z.enum(["strategy", "dataset", "symbol", "agent", "failure", "evaluation"]),
  scopeKey: z.string(),
  title: z.string(),
  memoryText: z.string(),
  evidenceJson: z.unknown(),
  confidence: z.number().min(0).max(1),
  active: z.boolean(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type ResearchMemory = z.infer<typeof researchMemorySchema>;
