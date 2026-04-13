import { z } from "zod";

export const executionModeSchema = z.enum(["testnet", "live"]);
export const venueSchema = z.literal("binance");
export const assetClassSchema = z.literal("spot");
export const orderTypeSchema = z.enum(["market", "limit"]);
export const orderSideSchema = z.enum(["buy", "sell"]);
export const runStatusSchema = z.enum(["success", "failure", "uncertain", "running"]);
export const executionStatusSchema = z.enum(["success", "failure", "uncertain"]);
export const decisionModeSchema = z.enum(["rebalance", "enter", "exit", "hold", "adjust"]);

export const runtimeConfigSchema = z.object({
  enabled: z.boolean(),
  venue: venueSchema,
  frequencyMinutes: z.enum(["1", "5", "15", "30", "60"]).transform(Number),
  mode: executionModeSchema,
  assetClass: assetClassSchema,
  execution: z.object({
    allowMarketOrders: z.boolean().default(true),
    allowLimitOrders: z.boolean().default(true),
    maxOrdersPerRun: z.number().int().positive().max(20).default(5),
    maxNotionalPerOrderUsd: z.number().positive().default(500),
    minCashReserveUsd: z.number().nonnegative().default(50)
  }),
  contextSymbols: z.array(z.string().min(3).max(20)).max(20).default([])
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
  rationale: z.string().min(1).max(400)
});

export type OrderIntent = z.infer<typeof orderIntentSchema>;

export const tradingDecisionSchema = z.object({
  mode: decisionModeSchema,
  rationaleSummary: z.string().min(1).max(600),
  globalRationale: z.string().min(1).max(4000),
  confidence: z.number().min(0).max(1),
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
          rationale: { type: "string" }
        },
        required: ["symbol", "side", "type", "quantity", "limitPrice", "rationale"]
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
  feeAmount: z.number().nullable(),
  feeAsset: z.string().nullable(),
  feeUsd: z.number().nullable(),
  slippagePct: z.number().nullable(),
  orderIntent: orderIntentSchema,
  rawVenueResponse: z.unknown()
});

export type ExecutionRecord = z.infer<typeof executionRecordSchema>;

export const botSummarySchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  slug: z.string(),
  enabled: z.boolean(),
  frequencyMinutes: z.number(),
  mode: executionModeSchema,
  assetClass: assetClassSchema,
  promptVersionLabel: z.string(),
  modelProfileName: z.string(),
  lastRunStatus: runStatusSchema.nullable(),
  latestDecisionSummary: z.string().nullable(),
  latestError: z.string().nullable(),
  updatedAt: z.string().datetime()
});

export type BotSummary = z.infer<typeof botSummarySchema>;

export const dashboardSchema = z.object({
  generatedAt: z.string().datetime(),
  bots: z.array(botSummarySchema),
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
