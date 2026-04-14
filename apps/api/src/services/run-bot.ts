import { loadVenueContext, executeOrders } from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  listBotExecutionLedger,
  markRunStarted,
  recentTradeAlerts,
  storeDecision,
  storeExecutionRecords,
  storeRawModelOutput,
  storePortfolioSnapshot,
  type BotSetup
} from "../lib/store.js";
import { DecisionParseError, extractCandidateSymbols, requestDecision, requestResearchPhase } from "../providers/xai.js";
import { getVenueSymbols } from "./catalog.js";
import { notifySlack } from "./notifier.js";
import { buildFormatterPhaseContext, buildResearchPhaseContext } from "./prompt-context.js";
import { validateDecision } from "./validator.js";
import { ALL_SYMBOLS_TOKEN, portfolioSnapshotSchema, type RuntimeConfig } from "@cosmu/shared";

const getDecisionWithRetry = async (
  bot: BotSetup,
  systemPrompt: string,
  userMessage: string
) => {
  let lastError: unknown;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await requestDecision({ bot, systemPrompt, userMessage });
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Decision request failed");
};

const getResearchWithRetry = async (
  bot: BotSetup,
  systemPrompt: string,
  userMessage: string
): Promise<{ rawText: string }> => {
  let lastError: unknown;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await requestResearchPhase({ bot, systemPrompt, userMessage });
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Research request failed");
};

const normalizePricingSymbol = (value: string) => value.replace(/[^A-Z0-9]/gi, "").toUpperCase();

const symbolsForPricing = (
  runtime: RuntimeConfig,
  held: string[],
  researchCandidates: string[]
): string[] => {
  const set = new Set<string>();
  for (const h of held) {
    const n = normalizePricingSymbol(h);
    if (n && n !== "USDTUSDT") set.add(n);
  }
  for (const c of researchCandidates) {
    const n = normalizePricingSymbol(c);
    if (n && n.endsWith("USDT") && n.length >= 8 && n !== "USDTUSDT") set.add(n);
  }
  for (const s of runtime.contextSymbols) {
    if (s === ALL_SYMBOLS_TOKEN) continue;
    const n = normalizePricingSymbol(s);
    if (n && n !== "USDTUSDT") set.add(n);
  }
  return Array.from(set);
};

const summarizeTrades = async (runId: string) => {
  const trades = await recentTradeAlerts(runId);
  if (trades.length === 0) {
    return "No executions";
  }

  return trades.map((trade) => `${trade.side} ${trade.symbol} (${trade.status})`).join(", ");
};

const computeAfterSnapshot = (input: {
  beforeSnapshot: Awaited<ReturnType<typeof loadVenueContext>>["snapshot"];
  afterSnapshot: Awaited<ReturnType<typeof loadVenueContext>>["snapshot"];
  totalFeeUsd: number;
}) => ({
  ...input.afterSnapshot,
  grossPnlUsd: input.afterSnapshot.totalUsdValue - input.beforeSnapshot.totalUsdValue,
  netPnlUsd: input.afterSnapshot.totalUsdValue - input.beforeSnapshot.totalUsdValue - input.totalFeeUsd,
  feeUsd: input.totalFeeUsd
});

type LogicalBalances = {
  usdt: number;
  assets: Record<string, number>;
};

const baseAssetFromSymbol = (symbol: string) => symbol.replace(/USDT$/i, "").toUpperCase();

const computeLogicalBalances = (
  budgetUsdt: number,
  ledger: Awaited<ReturnType<typeof listBotExecutionLedger>>
): LogicalBalances => {
  const balances: LogicalBalances = { usdt: budgetUsdt, assets: {} };

  for (const execution of ledger) {
    const quantity = execution.executedQuantity ?? 0;
    const notionalUsd = execution.executedNotionalUsd ?? 0;
    const feeAmount = execution.feeAmount ?? 0;
    const feeAsset = execution.feeAsset?.toUpperCase() ?? null;
    const baseAsset = baseAssetFromSymbol(execution.symbol);

    if (!(baseAsset in balances.assets)) {
      balances.assets[baseAsset] = 0;
    }

    if (execution.side === "buy") {
      balances.assets[baseAsset] += quantity;
      balances.usdt -= notionalUsd;
    } else {
      balances.assets[baseAsset] -= quantity;
      balances.usdt += notionalUsd;
    }

    if (feeAmount > 0 && feeAsset) {
      if (feeAsset === "USDT") {
        balances.usdt -= feeAmount;
      } else {
        balances.assets[feeAsset] = (balances.assets[feeAsset] ?? 0) - feeAmount;
      }
    }
  }

  return balances;
};

const getHeldSymbols = (logical: LogicalBalances) =>
  Object.entries(logical.assets)
    .filter(([, qty]) => Math.abs(qty) > 1e-8)
    .map(([asset]) => `${asset}USDT`);

const buildLogicalSnapshot = (input: {
  runtimeConfig: RuntimeConfig;
  logical: LogicalBalances;
  priceMap: Record<string, number>;
}) => {
  const balances = [
    {
      asset: "USDT",
      free: input.logical.usdt,
      locked: 0,
      usdValue: input.logical.usdt
    },
    ...Object.entries(input.logical.assets)
      .filter(([, qty]) => Math.abs(qty) > 1e-8)
      .map(([asset, quantity]) => {
        const price = input.priceMap[`${asset}USDT`];
        return {
          asset,
          free: quantity,
          locked: 0,
          usdValue: price ? quantity * price : null
        };
      })
  ];

  const totalUsdValue = balances.reduce((sum, balance) => sum + (balance.usdValue ?? 0), 0);

  return portfolioSnapshotSchema.parse({
    assetClass: input.runtimeConfig.assetClass,
    totalUsdValue,
    grossPnlUsd: null,
    netPnlUsd: null,
    feeUsd: null,
    balances,
    prices: Object.entries(input.priceMap).map(([symbol, price]) => ({ symbol, price })),
    capturedAt: new Date().toISOString()
  });
};

export const runBot = async (bot: BotSetup) => {
  await markRunStarted(bot.runtimeConfigId);

  let runId: string | null = null;

  try {
    const beforeLedger = await listBotExecutionLedger(bot.id);
    const beforeLogical = computeLogicalBalances(bot.runtimeConfig.budgetUsdt, beforeLedger);
    const initialSymbols = symbolsForPricing(bot.runtimeConfig, getHeldSymbols(beforeLogical), []);
    const beforeVenueRaw = await loadVenueContext(
      bot.runtimeConfig,
      initialSymbols.length > 0 ? initialSymbols : [...bot.runtimeConfig.contextSymbols, ...getHeldSymbols(beforeLogical)]
    );
    const beforeVenueContext = {
      ...beforeVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: beforeLogical,
        priceMap: beforeVenueRaw.priceMap
      })
    };

    const researchCtx = await buildResearchPhaseContext({
      bot,
      venueContext: beforeVenueContext
    });

    const { rawText: researchRaw } = await getResearchWithRetry(
      bot,
      researchCtx.systemPrompt,
      researchCtx.userMessage
    );

    const venueSymbols = await getVenueSymbols("binance");
    const candidateSymbols = extractCandidateSymbols(researchRaw, venueSymbols);

    const pricingSymbols = symbolsForPricing(bot.runtimeConfig, getHeldSymbols(beforeLogical), candidateSymbols);
    const pricedVenueRaw = await loadVenueContext(
      bot.runtimeConfig,
      pricingSymbols.length > 0
        ? pricingSymbols
        : [...bot.runtimeConfig.contextSymbols, ...getHeldSymbols(beforeLogical)]
    );
    const decisionVenueContext = {
      ...pricedVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: beforeLogical,
        priceMap: pricedVenueRaw.priceMap
      })
    };

    const priceSymbolFilter = new Set(pricingSymbols.map(normalizePricingSymbol));

    const formatterCtx = await buildFormatterPhaseContext({
      bot,
      venueContext: decisionVenueContext,
      researchRawText: researchRaw,
      candidateSymbols,
      priceSymbolFilter
    });

    const compactContext = {
      ...researchCtx.compactContext,
      formatter: formatterCtx.compactContext,
      researchCandidateSymbols: candidateSymbols
    };

    const promptSystem = [
      "=== PHASE 1 — RESEARCH (system) ===",
      researchCtx.systemPrompt,
      "",
      "=== PHASE 2 — FORMATTER (system) ===",
      formatterCtx.systemPrompt
    ].join("\n");

    const promptUser = [
      "=== PHASE 1 — RESEARCH (user context) ===",
      researchCtx.userMessage,
      "",
      "=== PHASE 2 — FORMATTER (user context) ===",
      formatterCtx.userMessage
    ].join("\n");

    runId = await createRun({
      botId: bot.id,
      promptVersionId: bot.promptVersionId,
      modelProfileId: bot.modelProfileId,
      runtimeConfig: bot.runtimeConfig,
      compactContext,
      promptSystem,
      promptUser
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    const { rawText: decisionRaw, decision } = await getDecisionWithRetry(
      bot,
      formatterCtx.systemPrompt,
      formatterCtx.userMessage
    );
    await storeRawModelOutput(
      runId,
      JSON.stringify(
        {
          phase1Research: researchRaw,
          phase2Decision: decisionRaw
        },
        null,
        2
      )
    );
    const validationResult = await validateDecision({
      decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: decisionVenueContext
    });

    await storeDecision({
      runId,
      rawModelOutput: decisionRaw,
      decision,
      validationResult
    });

    if (!validationResult.accepted) {
      await finishRun({
        runId,
        runtimeConfigId: bot.runtimeConfigId,
        status: "failure",
        errorState: { message: "Decision validation failed", issues: validationResult.issues }
      });
      await notifySlack(`Run failed for ${bot.name}: ${validationResult.issues.join("; ")}`);
      return { runId, status: "failure" as const, decision };
    }

    const executions = await executeOrders({
      runId,
      runtimeConfig: bot.runtimeConfig,
      orders: validationResult.normalizedOrders,
      venueContext: decisionVenueContext
    });

    await storeExecutionRecords(runId, executions);

    const afterLedger = await listBotExecutionLedger(bot.id);
    const afterLogical = computeLogicalBalances(bot.runtimeConfig.budgetUsdt, afterLedger);
    const afterVenueRaw = await loadVenueContext(bot.runtimeConfig, [
      ...bot.runtimeConfig.contextSymbols,
      ...getHeldSymbols(afterLogical)
    ]);
    const afterVenueContext = {
      ...afterVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: afterLogical,
        priceMap: afterVenueRaw.priceMap
      })
    };
    const totalFeeUsd = executions.reduce((sum, execution) => sum + (execution.feeUsd ?? 0), 0);
    const afterSnapshot = computeAfterSnapshot({
      beforeSnapshot: beforeVenueContext.snapshot,
      afterSnapshot: afterVenueContext.snapshot,
      totalFeeUsd
    });

    await storePortfolioSnapshot(runId, "after", afterSnapshot);

    const hasUncertain = executions.some((execution) => execution.status === "uncertain");
    const runStatus = hasUncertain ? "uncertain" : "success";

    await finishRun({
      runId,
      runtimeConfigId: bot.runtimeConfigId,
      status: runStatus,
      errorState: hasUncertain ? { message: "At least one execution result is uncertain" } : null
    });

    const tradeSummary = await summarizeTrades(runId);
    await notifySlack(`Run ${runStatus} for ${bot.name}: ${tradeSummary}`);

    return { runId, status: runStatus, decision };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown run error";

    if (runId) {
      if (error instanceof DecisionParseError) {
        await storeRawModelOutput(runId, error.rawText);
      } else {
        await storeRawModelOutput(
          runId,
          JSON.stringify(
            {
              providerError: errorMessage,
              at: new Date().toISOString()
            },
            null,
            2
          )
        );
      }
      await finishRun({
        runId,
        runtimeConfigId: bot.runtimeConfigId,
        status: "failure",
        errorState: { message: errorMessage }
      });
    }

    await notifySlack(`Run failure for ${bot.name}: ${errorMessage}`);
    throw error;
  }
};
