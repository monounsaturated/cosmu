import { z } from "zod";

export const ALL_SYMBOLS_TOKEN = "__ALL__";
export const executionModeSchema = z.enum(["testnet", "live"]);
export const venueSchema = z.enum(["binance", "binance-testnet"]);
export const assetClassSchema = z.literal("spot");
export const orderTypeSchema = z.enum(["market", "limit"]);
export const orderSideSchema = z.enum(["buy", "sell"]);
export const runStatusSchema = z.enum(["success", "failure", "uncertain", "running"]);
export const executionStatusSchema = z.enum(["success", "failure", "uncertain"]);
export const decisionModeSchema = z.enum(["rebalance", "enter", "exit", "hold", "adjust"]);
export const symbolScopeSchema = z.enum(["selected", "all"]);
export const sampleQualitySchema = z.enum(["low", "medium", "high"]);
export const workspaceModeSchema = z.enum(["light", "research", "pro"]);
export const agentStepStatusSchema = z.enum(["queued", "running", "success", "failure", "skipped"]);
export const agentScopeTypeSchema = z.enum(["light_run", "research_experiment", "paper_bot_run", "pro_run"]);
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

export const signalSourceKindSchema = z.enum(["x", "web", "news", "market", "manual"]);
export const signalDirectionSchema = z.enum(["bullish", "bearish", "neutral", "mixed"]);
export const signalUrgencySchema = z.enum(["low", "medium", "high"]);
export const signalStatusSchema = z.enum(["new", "watching", "used", "dismissed"]);

export const rawObservationSchema = z.object({
  id: z.string().uuid(),
  sourceKind: signalSourceKindSchema,
  sourceName: z.string(),
  sourceUrl: z.string().nullable(),
  observedAt: z.string().datetime(),
  capturedAt: z.string().datetime(),
  title: z.string(),
  content: z.string(),
  rawJson: z.unknown().nullable(),
  contentHash: z.string().nullable()
});

export type RawObservation = z.infer<typeof rawObservationSchema>;

export const standardizedSignalSchema = z.object({
  id: z.string().uuid(),
  observationId: z.string().uuid().nullable(),
  asset: z.string(),
  symbol: z.string().nullable(),
  topic: z.string(),
  direction: signalDirectionSchema,
  sentimentScore: z.number().min(-1).max(1),
  confidence: z.number().min(0).max(1),
  urgency: signalUrgencySchema,
  horizon: z.string().nullable(),
  summary: z.string(),
  evidenceJson: z.unknown(),
  reasoningSummary: z.string().nullable(),
  status: signalStatusSchema,
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime()
});

export type StandardizedSignal = z.infer<typeof standardizedSignalSchema>;

export const researchEngineSchema = z.enum(["native", "hermes", "autoresearch", "openclaw"]);
export type ResearchEngine = z.infer<typeof researchEngineSchema>;
export const researchAutonomyModeSchema = z.enum(["manual", "assisted", "autonomous"]);
export const researchSessionStatusSchema = z.enum(["draft", "queued", "running", "success", "failure", "stopped"]);
export const engineRunStatusSchema = z.enum(["queued", "running", "success", "failure", "cancelled"]);
export const evaluationJobStatusSchema = z.enum(["queued", "running", "success", "failure", "cancelled"]);
export const evaluationKindSchema = z.enum(["paper_backtest", "ml_validation"]);

export const prePromptModulesSchema = z.object({
  includeCurrentPositions: z.boolean().default(true),
  includePastTrades: z.boolean().default(false),
  pastTradesLookback: z.number().int().min(1).max(200).default(10),
  includePerformanceStats: z.boolean().default(true),
  includeBotRanking: z.boolean().default(false),
  includeWalletOverview: z.boolean().default(true)
});

export const prePromptConfigSchema = z
  .object({
    preset: z.string().optional(),
    modules: prePromptModulesSchema.default({
      includeCurrentPositions: true,
      includePastTrades: false,
      pastTradesLookback: 10,
      includePerformanceStats: true,
      includeBotRanking: false,
      includeWalletOverview: true
    })
  })
  .transform((val) => ({
    modules: val.modules
  }));

export const traderConfigSchema = z.object({
  mode: z.literal("deterministic").default("deterministic"),
  modelProfileId: z.string().uuid().nullable().default(null)
});

export type PrePromptConfig = z.infer<typeof prePromptConfigSchema>;
export type TraderConfig = z.infer<typeof traderConfigSchema>;

export const llmProviderSchema = z.enum(["xai", "nous", "openai", "anthropic", "huggingface", "google", "mistral"]);
export type LlmProvider = z.infer<typeof llmProviderSchema>;

const DEFAULT_PROMPT_DEFAULT = { mode: "new", versionId: null } as const;
const DEFAULT_SAVED_PROMPT_DEFAULT = { mode: "saved", versionId: null } as const;
const DEFAULT_PHASE_DEFAULT = { provider: "xai", modelProfileId: null, prompt: DEFAULT_PROMPT_DEFAULT } as const;
const DEFAULT_TRADER_PHASE_DEFAULT = { provider: "xai", modelProfileId: null, prompt: DEFAULT_SAVED_PROMPT_DEFAULT } as const;
const DEFAULT_RUNTIME_EXECUTION = {
  enabled: false,
  allowMarketOrders: true,
  allowLimitOrders: true,
  maxOrdersPerRun: 3,
  maxNotionalPerOrderUsd: 250,
  minCashReserveUsd: 25,
  maxDrawdownPct: 10
} as const;
const DEFAULT_RUNTIME_DEFAULTS = {
  venue: "binance-testnet",
  frequencyMinutes: 30,
  budgetUsdt: 1000,
  symbolScope: "all",
  execution: DEFAULT_RUNTIME_EXECUTION
} as const;
const DEFAULT_FEATURE_TOGGLES = {
  promptLab: false,
  sentiment: false,
  signals: false,
  researchLab: false,
  proReview: false,
  promptLibrary: false
} as const;

export const promptDefaultSchema = z.object({
  mode: z.enum(["new", "saved"]).default("new"),
  versionId: z.string().uuid().nullable().default(null)
}).default(DEFAULT_PROMPT_DEFAULT);

export const phaseDefaultSchema = z.object({
  provider: llmProviderSchema.default("xai"),
  modelProfileId: z.string().uuid().nullable().default(null),
  prompt: promptDefaultSchema
}).default(DEFAULT_PHASE_DEFAULT);

export const agentRuntimeDefaultsSchema = z.object({
  venue: venueSchema.default("binance-testnet"),
  frequencyMinutes: z.number().int().positive().default(30),
  budgetUsdt: z.number().positive().default(1000),
  symbolScope: symbolScopeSchema.default("all"),
  execution: z.object({
    enabled: z.boolean().default(false),
    allowMarketOrders: z.boolean().default(true),
    allowLimitOrders: z.boolean().default(true),
    maxOrdersPerRun: z.number().int().positive().max(20).default(3),
    maxNotionalPerOrderUsd: z.number().positive().default(250),
    minCashReserveUsd: z.number().nonnegative().default(25),
    maxDrawdownPct: z.number().positive().max(100).default(10)
  }).default(DEFAULT_RUNTIME_EXECUTION)
}).default(DEFAULT_RUNTIME_DEFAULTS);

export const featureTogglesSchema = z.object({
  promptLab: z.boolean().default(false),
  sentiment: z.boolean().default(false),
  signals: z.boolean().default(false),
  researchLab: z.boolean().default(false),
  proReview: z.boolean().default(false),
  promptLibrary: z.boolean().default(false)
}).default(DEFAULT_FEATURE_TOGGLES);

export const appSettingsSchema = z.object({
  agentDefaults: z.object({
    research: phaseDefaultSchema.default(DEFAULT_PHASE_DEFAULT),
    trader: phaseDefaultSchema.default(DEFAULT_TRADER_PHASE_DEFAULT),
    runtime: agentRuntimeDefaultsSchema.default(DEFAULT_RUNTIME_DEFAULTS)
  }).default({
    research: DEFAULT_PHASE_DEFAULT,
    trader: DEFAULT_TRADER_PHASE_DEFAULT,
    runtime: DEFAULT_RUNTIME_DEFAULTS
  }),
  featureToggles: featureTogglesSchema.default(DEFAULT_FEATURE_TOGGLES)
});

export type AppSettings = z.infer<typeof appSettingsSchema>;
export const defaultAppSettings: AppSettings = appSettingsSchema.parse({});

export const runtimeConfigSchema = z.object({
  enabled: z.boolean(),
  venue: venueSchema,
  frequencyMinutes: z.preprocess(
    (v) => String(v),
    z.enum(["1", "5", "15", "30", "60", "240", "720", "1440"])
  ).transform(Number),
  mode: executionModeSchema,
  assetClass: assetClassSchema,
  budgetUsdt: z.number().positive().default(1000),
  symbolScope: symbolScopeSchema.default("selected"),
  execution: z.object({
    enabled: z.boolean().default(false),
    allowMarketOrders: z.boolean().default(true),
    allowLimitOrders: z.boolean().default(true),
    maxOrdersPerRun: z.number().int().positive().max(20).default(5),
    maxNotionalPerOrderUsd: z.number().positive().default(500),
    minCashReserveUsd: z.number().nonnegative().default(50),
    maxDrawdownPct: z.number().positive().max(100).default(10)
  }),
  contextSymbols: z.array(z.string().min(3).max(20)).max(200).default([])
});

export type RuntimeConfig = z.infer<typeof runtimeConfigSchema>;

export const walletBalanceSchema = z.object({
  asset: z.string(),
  free: z.number(),
  locked: z.number(),
  usdValue: z.number().nullable()
});

export const pricePointSchema = z.object({
  symbol: z.string(),
  price: z.number()
});

export const portfolioSnapshotSchema = z.object({
  assetClass: assetClassSchema,
  totalUsdValue: z.number(),
  grossPnlUsd: z.number().nullable(),
  netPnlUsd: z.number().nullable(),
  feeUsd: z.number().nullable(),
  balances: z.array(walletBalanceSchema),
  prices: z.array(pricePointSchema),
  capturedAt: z.string().datetime()
});

export type PortfolioSnapshot = z.infer<typeof portfolioSnapshotSchema>;

export const orderIntentSchema = z.object({
  symbol: z.string().min(6).max(20),
  side: orderSideSchema,
  type: orderTypeSchema,
  quantity: z.number().positive(),
  limitPrice: z.number().positive().nullable().default(null),
  stopLossPrice: z.number().positive().nullable().default(null),
  takeProfitPrice: z.number().positive().nullable().default(null),
  rationale: z.string().min(1).max(400)
});

export type OrderIntent = z.infer<typeof orderIntentSchema>;

/** @deprecated Phase 1 now returns free-form text. Kept for backward compatibility of stored run data. */
export const researchPhaseSchema = z.object({
  rationaleSummary: z.string().min(1).max(600),
  globalResearch: z.string().min(1).max(8000),
  candidateSymbols: z.array(z.string().min(6).max(24)).max(20).default([])
});

/** @deprecated Phase 1 now returns free-form text. Kept for backward compatibility of stored run data. */
export type ResearchPhase = z.infer<typeof researchPhaseSchema>;

/** @deprecated Phase 1 no longer uses structured JSON output. Kept for backward compatibility. */
export const researchPhaseJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    rationaleSummary: { type: "string" },
    globalResearch: { type: "string" },
    candidateSymbols: {
      type: "array",
      items: { type: "string", minLength: 6, maxLength: 24 },
      maxItems: 20
    }
  },
  required: ["rationaleSummary", "globalResearch", "candidateSymbols"]
} as const;

export const tradingDecisionSchema = z.object({
  mode: decisionModeSchema,
  rationaleSummary: z.string().min(1).max(600),
  globalRationale: z.string().min(1).max(4000),
  confidence: z.preprocess(
    (v) => Math.max(0, Math.min(1, Number(v) || 0)),
    z.number().min(0).max(1)
  ),
  timeHorizon: z.string().min(1).max(120).nullable().default(null),
  orders: z.array(orderIntentSchema).max(20),
  targetAllocations: z
    .array(
      z.object({
        asset: z.string(),
        targetWeight: z.number().min(0).max(1)
      })
    )
    .max(20)
    .default([])
});

export type TradingDecision = z.infer<typeof tradingDecisionSchema>;

export const tradingDecisionJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    mode: {
      type: "string",
      enum: ["rebalance", "enter", "exit", "hold", "adjust"]
    },
    rationaleSummary: {
      type: "string"
    },
    globalRationale: {
      type: "string"
    },
    confidence: {
      type: "number"
    },
    timeHorizon: {
      type: ["string", "null"]
    },
    orders: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        properties: {
          symbol: { type: "string" },
          side: { type: "string", enum: ["buy", "sell"] },
          type: { type: "string", enum: ["market", "limit"] },
          quantity: { type: "number" },
          limitPrice: { type: ["number", "null"] },
          stopLossPrice: { type: ["number", "null"] },
          takeProfitPrice: { type: ["number", "null"] },
          rationale: { type: "string" }
        },
        required: ["symbol", "side", "type", "quantity", "limitPrice", "stopLossPrice", "takeProfitPrice", "rationale"]
      }
    },
    targetAllocations: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        properties: {
          asset: { type: "string" },
          targetWeight: { type: "number" }
        },
        required: ["asset", "targetWeight"]
      }
    }
  },
  required: [
    "mode",
    "rationaleSummary",
    "globalRationale",
    "confidence",
    "timeHorizon",
    "orders",
    "targetAllocations"
  ]
} as const;

export const validationResultSchema = z.object({
  accepted: z.boolean(),
  issues: z.array(z.string()),
  normalizedOrders: z.array(orderIntentSchema)
});

export type ValidationResult = z.infer<typeof validationResultSchema>;

export const executionRecordSchema = z.object({
  assetClass: assetClassSchema,
  venue: venueSchema,
  status: executionStatusSchema,
  symbol: z.string(),
  side: orderSideSchema,
  orderType: orderTypeSchema,
  requestedQuantity: z.number(),
  executedQuantity: z.number().nullable(),
  requestedLimitPrice: z.number().nullable(),
  averageFillPrice: z.number().nullable(),
  executedNotionalUsd: z.number().nullable().default(null),
  feeAmount: z.number().nullable(),
  feeAsset: z.string().nullable(),
  feeAssetUsdPrice: z.number().nullable().default(null),
  feeUsd: z.number().nullable(),
  slippagePct: z.number().nullable(),
  stopLossPrice: z.number().nullable().default(null),
  takeProfitPrice: z.number().nullable().default(null),
  ocoOrderId: z.string().nullable().default(null),
  orderIntent: orderIntentSchema,
  rawVenueResponse: z.unknown()
});

export type ExecutionRecord = z.infer<typeof executionRecordSchema>;

export const agentStepSchema = z.object({
  id: z.string().uuid(),
  scopeType: agentScopeTypeSchema,
  scopeId: z.string().uuid(),
  agentKey: z.string(),
  agentLabel: z.string(),
  status: agentStepStatusSchema,
  inputJson: z.unknown().nullable(),
  outputText: z.string().nullable(),
  outputJson: z.unknown().nullable(),
  toolCalls: z.unknown().nullable(),
  modelProvider: z.string().nullable(),
  model: z.string().nullable(),
  inputTokens: z.number().nullable(),
  outputTokens: z.number().nullable(),
  latencyMs: z.number().nullable(),
  error: z.string().nullable(),
  startedAt: z.string().datetime(),
  finishedAt: z.string().datetime().nullable()
});

export type AgentStep = z.infer<typeof agentStepSchema>;

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

export const approvalRequestSchema = z.object({
  id: z.string().uuid(),
  requestType: z.enum(["live_promotion", "dangerous_action", "connector_permission"]),
  status: z.enum(["pending", "approved", "rejected", "cancelled"]),
  title: z.string(),
  body: z.string().nullable(),
  payload: z.unknown(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  resolvedAt: z.string().datetime().nullable()
});

export type ApprovalRequest = z.infer<typeof approvalRequestSchema>;

export const botSummarySchema = z.object({
  id: z.string().uuid(),
  botNumber: z.number().int().positive(),
  name: z.string(),
  slug: z.string(),
  enabled: z.boolean(),
  workspaceMode: workspaceModeSchema.default("light"),
  venue: venueSchema,
  frequencyMinutes: z.number(),
  mode: executionModeSchema,
  assetClass: assetClassSchema,
  budgetUsdt: z.number().positive().default(1000),
  promptVersionLabel: z.string(),
  traderPromptVersionLabel: z.string().nullable().optional(),
  modelProfileName: z.string(),
  researchModelName: z.string().optional(),
  researchModelProvider: z.string().optional(),
  traderModelName: z.string().optional(),
  traderModelProvider: z.string().optional(),
  lastRunStatus: runStatusSchema.nullable(),
  latestDecisionSummary: z.string().nullable(),
  latestError: z.string().nullable(),
  startedAt: z.string().datetime(),
  daysRunning: z.number().nonnegative(),
  runCount: z.number().int().nonnegative(),
  tradeCount: z.number().int().nonnegative(),
  avgTradesPerDay: z.number().nonnegative(),
  totalFeesUsd: z.number().nullable(),
  grossPnlUsd: z.number().nullable(),
  netPnlUsd: z.number().nullable(),
  currentPortfolioUsd: z.number().nullable(),
  sampleQuality: sampleQualitySchema,
  updatedAt: z.string().datetime()
});

export type BotSummary = z.infer<typeof botSummarySchema>;

export const botPerformancePointSchema = z.object({
  at: z.string().datetime(),
  totalUsdValue: z.number(),
  normalizedValue: z.number()
});

export const botPerformanceSeriesSchema = z.object({
  botId: z.string().uuid(),
  botName: z.string(),
  botNumber: z.number().int().positive(),
  points: z.array(botPerformancePointSchema)
});

const venueOverviewEntrySchema = z.object({
  accountBalance: z.number(),
  allocatedAmount: z.number(),
  spareAmount: z.number()
});

const accountOverviewEntrySchema = venueOverviewEntrySchema.extend({
  id: z.string(),
  label: z.string(),
  venue: z.string(),
  mode: z.string(),
  connected: z.boolean(),
  configuredAgents: z.number().int().nonnegative(),
  activeAgents: z.number().int().nonnegative(),
  status: z.enum(["connected", "configured", "unconfigured", "error"])
});

export const dashboardSchema = z.object({
  generatedAt: z.string().datetime(),
  venueOverview: z.object({
    live: venueOverviewEntrySchema.nullable(),
    testnet: venueOverviewEntrySchema.nullable()
  }),
  accounts: z.array(accountOverviewEntrySchema).default([]),
  bots: z.array(botSummarySchema),
  performanceSeries: z.array(botPerformanceSeriesSchema),
  recentRuns: z.array(
    z.object({
      id: z.string().uuid(),
      botName: z.string(),
      status: runStatusSchema,
      startedAt: z.string().datetime(),
      finishedAt: z.string().datetime().nullable(),
      decisionMode: decisionModeSchema.nullable(),
      rationaleSummary: z.string().nullable()
    })
  ),
  recentExecutions: z.array(executionRecordSchema.extend({ runId: z.string().uuid() })),
  latestSnapshots: z.array(
    z.object({
      botId: z.string().uuid(),
      botName: z.string(),
      snapshot: portfolioSnapshotSchema
    })
  ),
  promptVersions: z.array(
    z.object({
      promptName: z.string(),
      version: z.number(),
      label: z.string(),
      createdAt: z.string().datetime()
    })
  )
});

export type DashboardPayload = z.infer<typeof dashboardSchema>;
