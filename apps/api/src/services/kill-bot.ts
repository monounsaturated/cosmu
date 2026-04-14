import { executeOrders, loadVenueContext, cancelAllOpenOrdersForSymbol } from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  killBot,
  listBotExecutionLedger,
  markRunStarted,
  storeDecision,
  storeExecutionRecords,
  storePortfolioSnapshot,
  type BotSetup
} from "../lib/store.js";
import { notifySlack } from "./notifier.js";
import { validateDecision } from "./validator.js";
import { portfolioSnapshotSchema, type RuntimeConfig, type TradingDecision } from "@cosmu/shared";

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

const buildKillDecision = (orders: TradingDecision["orders"]): TradingDecision => ({
  mode: "exit",
  rationaleSummary: "Kill mode liquidation",
  globalRationale:
    "Kill mode requested by operator. Liquidating all currently held spot positions and stopping this bot permanently.",
  confidence: 1,
  timeHorizon: null,
  orders,
  targetAllocations: []
});

export const killBotAndLiquidate = async (bot: BotSetup) => {
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

    runId = await createRun({
      botId: bot.id,
      promptVersionId: bot.promptVersionId,
      modelProfileId: bot.modelProfileId,
      runtimeConfig: bot.runtimeConfig,
      compactContext: {
        mode: "kill",
        reason: "manual liquidate and stop"
      },
      promptSystem:
        "Kill mode execution. No model call. Liquidate all held symbols and permanently disable this bot.",
      promptUser: "Operator requested kill mode liquidation."
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    for (const balance of beforeVenueRaw.snapshot.balances) {
      const asset = balance.asset.toUpperCase();
      if (asset === "USDT") {
        continue;
      }

      const totalQty = Number(balance.free) + Number(balance.locked);
      if (!Number.isFinite(totalQty) || totalQty <= 1e-8) {
        continue;
      }

      await cancelAllOpenOrdersForSymbol(bot.runtimeConfig.mode, `${asset}USDT`);
    }

    const refreshedVenue = await loadVenueContext(bot.runtimeConfig, bot.runtimeConfig.contextSymbols);
    const sellOrders = refreshedVenue.snapshot.balances
      .filter((balance) => balance.asset.toUpperCase() !== "USDT" && Number(balance.free) > 1e-8)
      .map((balance) => ({
        symbol: `${balance.asset.toUpperCase()}USDT`,
        side: "sell" as const,
        type: "market" as const,
        quantity: Number(balance.free),
        limitPrice: null,
        stopLossPrice: null,
        takeProfitPrice: null,
        rationale: "Kill mode liquidation"
      }));

    const decision = buildKillDecision(sellOrders);
    const validationResult = await validateDecision({
      decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: refreshedVenue
    });

    await storeDecision({
      runId,
      rawModelOutput: JSON.stringify(decision),
      decision,
      validationResult
    });

    if (!validationResult.accepted) {
      await finishRun({
        runId,
        runtimeConfigId: bot.runtimeConfigId,
        status: "failure",
        errorState: { message: "Kill liquidation validation failed", issues: validationResult.issues }
      });
      return { runId, status: "failure" as const, issues: validationResult.issues };
    }

    const executions = await executeOrders({
      runId,
      runtimeConfig: bot.runtimeConfig,
      orders: validationResult.normalizedOrders,
      venueContext: refreshedVenue
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
      errorState: hasUncertain ? { message: "At least one liquidation execution is uncertain" } : null
    });
    await killBot(bot.id);

    await notifySlack(`Bot ${bot.name} killed. Liquidation run ${runStatus}.`);

    return { runId, status: runStatus, killed: true as const };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown kill error";
    if (runId) {
      await finishRun({
        runId,
        runtimeConfigId: bot.runtimeConfigId,
        status: "failure",
        errorState: { message: errorMessage }
      });
    }
    await notifySlack(`Kill mode failure for ${bot.name}: ${errorMessage}`);
    throw error;
  }
};
