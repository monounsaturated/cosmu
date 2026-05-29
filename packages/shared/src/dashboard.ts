// module: Dashboard + bot summary + LLM spend payloads (read models for the web UI).
import { z } from "zod";
import { assetClassSchema, venueSchema } from "./venue.js";
import {
  decisionModeSchema,
  executionRecordSchema,
  portfolioSnapshotSchema,
  runStatusSchema,
  sampleQualitySchema
} from "./trading.js";

export const botSummarySchema = z.object({
  id: z.string().uuid(),
  botNumber: z.number().int().positive(),
  name: z.string(),
  slug: z.string(),
  enabled: z.boolean(),
  venue: venueSchema,
  frequencyMinutes: z.number(),
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

export const llmSpendEstimateSchema = z.object({
  generatedAt: z.string().datetime(),
  currency: z.literal("USD"),
  activeBotCount: z.number().int().nonnegative(),
  pricedBotCount: z.number().int().nonnegative(),
  unknownBotCount: z.number().int().nonnegative(),
  sampleWindowRuns: z.number().int().positive(),
  estimatedHourlyUsd: z.number().nonnegative(),
  estimatedDailyUsd: z.number().nonnegative(),
  estimatedMonthlyUsd: z.number().nonnegative(),
  observedSampleUsd: z.number().nonnegative(),
  pricingUpdatedAt: z.string().datetime(),
  pricingSource: z.string(),
  note: z.string(),
  assumptions: z.array(
    z.object({
      provider: z.string(),
      model: z.string(),
      inputUsdPerMillion: z.number().nonnegative(),
      outputUsdPerMillion: z.number().nonnegative(),
      sourceUrl: z.string().url(),
      fetchedAt: z.string().datetime().nullable(),
      note: z.string().nullable()
    })
  ),
  bots: z.array(
    z.object({
      botId: z.string().uuid(),
      botNumber: z.number().int().positive(),
      name: z.string(),
      frequencyMinutes: z.number().positive(),
      runsPerHour: z.number().nonnegative(),
      sampleRunCount: z.number().int().nonnegative(),
      sampleCallCount: z.number().int().nonnegative(),
      sampleInputTokens: z.number().int().nonnegative(),
      sampleOutputTokens: z.number().int().nonnegative(),
      estimatedCostPerRunUsd: z.number().nonnegative().nullable(),
      estimatedHourlyUsd: z.number().nonnegative().nullable(),
      estimatedDailyUsd: z.number().nonnegative().nullable(),
      pricingKnown: z.boolean(),
      warning: z.string().nullable(),
      providers: z.array(
        z.object({
          provider: z.string(),
          model: z.string(),
          inputTokens: z.number().int().nonnegative(),
          outputTokens: z.number().int().nonnegative(),
          callCount: z.number().int().nonnegative(),
          estimatedUsd: z.number().nonnegative().nullable(),
          pricingKnown: z.boolean()
        })
      )
    })
  )
});

export type LlmSpendEstimate = z.infer<typeof llmSpendEstimateSchema>;

export const llmSpendOverviewSchema = z.object({
  generatedAt: z.string().datetime(),
  currency: z.literal("USD"),
  estimate: llmSpendEstimateSchema,
  totals: z.object({
    allTimeUsd: z.number().nonnegative().nullable(),
    last24hUsd: z.number().nonnegative().nullable(),
    last7dUsd: z.number().nonnegative().nullable(),
    last30dUsd: z.number().nonnegative().nullable(),
    callCount: z.number().int().nonnegative(),
    inputTokens: z.number().int().nonnegative(),
    outputTokens: z.number().int().nonnegative(),
    unknownCostCallCount: z.number().int().nonnegative()
  }),
  topBots: z.array(
    z.object({
      botId: z.string().uuid(),
      botNumber: z.number().int().positive(),
      name: z.string(),
      enabled: z.boolean(),
      frequencyMinutes: z.number().positive().nullable(),
      totalUsd: z.number().nonnegative().nullable(),
      last24hUsd: z.number().nonnegative().nullable(),
      callCount: z.number().int().nonnegative(),
      inputTokens: z.number().int().nonnegative(),
      outputTokens: z.number().int().nonnegative(),
      lastCallAt: z.string().datetime().nullable(),
      estimatedCostPerRunUsd: z.number().nonnegative().nullable(),
      estimatedHourlyUsd: z.number().nonnegative().nullable()
    })
  ),
  recentRuns: z.array(
    z.object({
      runId: z.string().uuid(),
      botId: z.string().uuid(),
      botNumber: z.number().int().positive(),
      botName: z.string(),
      status: runStatusSchema,
      startedAt: z.string().datetime(),
      finishedAt: z.string().datetime().nullable(),
      totalUsd: z.number().nonnegative().nullable(),
      callCount: z.number().int().nonnegative(),
      inputTokens: z.number().int().nonnegative(),
      outputTokens: z.number().int().nonnegative()
    })
  ),
  pricing: z.object({
    updatedAt: z.string().datetime(),
    source: z.string(),
    assumptions: llmSpendEstimateSchema.shape.assumptions
  })
});

export type LlmSpendOverview = z.infer<typeof llmSpendOverviewSchema>;

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
  configured: z.boolean().optional(),
  connected: z.boolean(),
  checkedAt: z.string().datetime().optional(),
  configuredAgents: z.number().int().nonnegative(),
  activeAgents: z.number().int().nonnegative(),
  status: z.enum(["connected", "configured", "unconfigured", "error"]),
  error: z.string().nullable().optional()
});

const marketDataModeStatusSchema = z.object({
  pricesUpdatedAt: z.string().datetime().nullable(),
  balanceUpdatedAt: z.string().datetime().nullable(),
  pricesError: z.string().nullable(),
  balanceError: z.string().nullable(),
  stale: z.boolean()
});

export const dashboardSchema = z.object({
  generatedAt: z.string().datetime(),
  backendError: z.string().optional(),
  marketDataStatus: z.object({
    live: marketDataModeStatusSchema,
    testnet: marketDataModeStatusSchema
  }).optional(),
  venueOverview: z.object({
    live: venueOverviewEntrySchema.nullable(),
    testnet: venueOverviewEntrySchema.nullable()
  }),
  accounts: z.array(accountOverviewEntrySchema).default([]),
  bots: z.array(botSummarySchema),
  llmSpendEstimate: llmSpendEstimateSchema.nullable().default(null),
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
