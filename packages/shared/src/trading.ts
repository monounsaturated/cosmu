// module: Trading domain — runtime config, decisions, validation, execution records.
import { z } from "zod";
import { assetClassSchema, venueSchema } from "./venue.js";

export const orderTypeSchema = z.enum(["market", "limit"]);
export const orderSideSchema = z.enum(["buy", "sell"]);
export const runStatusSchema = z.enum(["success", "failure", "uncertain", "running"]);
export const executionStatusSchema = z.enum(["success", "failure", "uncertain"]);
export const decisionModeSchema = z.enum(["rebalance", "enter", "exit", "hold", "adjust"]);
export const symbolScopeSchema = z.enum(["selected", "all"]);
export const sampleQualitySchema = z.enum(["low", "medium", "high"]);

export const prePromptModulesSchema = z.object({
  includeCurrentPositions: z.boolean().default(true),
  includePastTrades: z.boolean().default(false),
  pastTradesLookback: z.number().int().min(1).max(200).default(10),
  includePerformanceStats: z.boolean().default(false),
  includeBotRanking: z.boolean().default(false),
  includeWalletOverview: z.boolean().default(false)
});

export const prePromptConfigSchema = z
  .object({
    preset: z.string().optional(),
    modules: prePromptModulesSchema.default({
      includeCurrentPositions: true,
      includePastTrades: false,
      pastTradesLookback: 10,
      includePerformanceStats: false,
      includeBotRanking: false,
      includeWalletOverview: false
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

export const runtimeConfigSchema = z.object({
  enabled: z.boolean(),
  venue: venueSchema,
  frequencyMinutes: z.preprocess(
    (v) => String(v),
    z.enum(["1", "5", "15", "30", "60", "240", "720", "1440"])
  ).transform(Number),
  assetClass: assetClassSchema,
  budgetUsdt: z.number().positive().default(1000),
  symbolScope: symbolScopeSchema.default("selected"),
  execution: z.object({
    enabled: z.boolean().default(false),
    maxDrawdownEnabled: z.boolean().default(false),
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
