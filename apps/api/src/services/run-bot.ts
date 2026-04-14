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
import { DecisionParseError, requestDecision } from "../providers/xai.js";
import { notifySlack } from "./notifier.js";
import { buildPromptContext } from "./prompt-context.js";
import { validateDecision } from "./validator.js";
import { portfolioSnapshotSchema, type RuntimeConfig } from "@cosmu/shared";

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
    const beforeVenueRaw = await loadVenueContext(bot.runtimeConfig, [
      ...bot.runtimeConfig.contextSymbols,
      ...getHeldSymbols(beforeLogical)
    ]);
    const beforeVenueContext = {
      ...beforeVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: beforeLogical,
        priceMap: beforeVenueRaw.priceMap
      })
    };
    const { systemPrompt, userMessage, compactContext } = await buildPromptContext({
      bot,
      venueContext: beforeVenueContext
    });

    runId = await createRun({
      botId: bot.id,
      promptVersionId: bot.promptVersionId,
      modelProfileId: bot.modelProfileId,
      runtimeConfig: bot.runtimeConfig,
      compactContext,
      promptSystem: systemPrompt,
      promptUser: userMessage
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    const { rawText, decision } = await getDecisionWithRetry(bot, systemPrompt, userMessage);
    await storeRawModelOutput(runId, rawText);
    const validationResult = await validateDecision({
      decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: beforeVenueContext
    });

    await storeDecision({
      runId,
      rawModelOutput: rawText,
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
      venueContext: beforeVenueContext
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
