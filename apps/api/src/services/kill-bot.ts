import { executeOrders, loadVenueContext, cancelAllOpenOrdersForSymbol } from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  killBot,
  listBotExecutionLedger,
  storeDecision,
  storeExecutionRecords,
  storePortfolioSnapshot,
  applySellToOpenPositions,
  type BotSetup
} from "../lib/store.js";
import {
  computeLogicalBalances,
  buildLogicalSnapshot,
  getHeldSymbols,
  computeAfterSnapshot
} from "../lib/logical-balances.js";
import { notifySlack } from "./notifier.js";
import { validateDecision } from "./validator.js";
import { type TradingDecision } from "@cosmu/shared";

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

/**
 * Kill a bot and attempt to liquidate its positions.
 *
 * The bot is disabled FIRST so the scheduler can never pick it up again.
 * Liquidation is best-effort — if it fails the bot is still killed.
 * This function never throws; it always returns a result object.
 */
export const killBotAndLiquidate = async (bot: BotSetup) => {
  // ── Step 1: disable the bot immediately ──────────────────────────────
  // killBot flips enabled=false so the scheduler can never pick it up again; no claim needed.
  await killBot(bot.id);

  // ── Step 2: best-effort liquidation ──────────────────────────────────
  let runId: string | null = null;

  try {
    const beforeLedger = await listBotExecutionLedger(bot.id);
    const beforeLogical = computeLogicalBalances(bot.runtimeConfig.budgetUsdt, beforeLedger);
    const heldSymbols = getHeldSymbols(beforeLogical);
    const beforeVenueRaw = await loadVenueContext(bot.runtimeConfig, [
      ...bot.runtimeConfig.contextSymbols,
      ...heldSymbols
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
      compactContext: { mode: "kill", reason: "manual liquidate and stop" },
      promptSystem:
        "Kill mode execution. No model call. Liquidate all held symbols and permanently disable this bot.",
      promptUser: "Operator requested kill mode liquidation."
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    // Cancel open orders for symbols this bot logically holds.
    // This frees locked balances from OCO (SL/TP) orders.
    for (const symbol of heldSymbols) {
      try {
        await cancelAllOpenOrdersForSymbol(bot.runtimeConfig.mode, symbol);
      } catch (cancelError) {
        console.warn(`kill-bot: cancel orders for ${symbol} failed, continuing:`, cancelError);
      }
    }

    // Wait for Binance to settle after cancellations (frees locked balances)
    if (heldSymbols.length > 0) {
      await wait(500);
    }

    // Reload venue context after cancellations so free balances are up-to-date
    const freshVenueRaw = await loadVenueContext(bot.runtimeConfig, [
      ...bot.runtimeConfig.contextSymbols,
      ...heldSymbols
    ]);
    const freshVenueContext = {
      ...freshVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: beforeLogical,
        priceMap: freshVenueRaw.priceMap
      })
    };

    // Build sell orders from logical balances — only what this bot actually bought
    const sellOrders = Object.entries(beforeLogical.assets)
      .filter(([asset, qty]) => asset.length > 0 && qty > 1e-8)
      .map(([asset, qty]) => ({
        symbol: `${asset}USDT`,
        side: "sell" as const,
        type: "market" as const,
        quantity: qty,
        limitPrice: null,
        stopLossPrice: null,
        takeProfitPrice: null,
        rationale: "Kill mode liquidation"
      }));

    const decision = buildKillDecision(sellOrders);
    const validationResult = await validateDecision({
      decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: freshVenueContext
    });

    await storeDecision({
      runId,
      decision,
      validationResult
    });

    // In kill mode: execute whatever orders passed validation, even if some failed.
    // Don't abort the entire kill because one symbol is untradable.
    const ordersToExecute = validationResult.normalizedOrders;

    if (validationResult.issues.length > 0) {
      console.warn(`kill-bot: validation issues (executing ${ordersToExecute.length} valid orders anyway):`, validationResult.issues);
    }

    let executions: Awaited<ReturnType<typeof executeOrders>> = [];

    if (ordersToExecute.length > 0) {
      executions = await executeOrders({
        runId,
        runtimeConfig: bot.runtimeConfig,
        orders: ordersToExecute,
        venueContext: freshVenueContext
      });
    }

    const storedExecutions = await storeExecutionRecords(runId, executions);

    // Kill-mode sells also need to FIFO-close positions so the ledger stays consistent.
    for (const { id: executionId, record } of storedExecutions) {
      if (record.status !== "success" || record.side !== "sell") continue;
      const qty = record.executedQuantity ?? 0;
      const price = record.averageFillPrice ?? record.requestedLimitPrice ?? null;
      if (qty <= 0 || !price) continue;
      try {
        await applySellToOpenPositions({
          botId: bot.id,
          symbol: record.symbol,
          sellQuantity: qty,
          sellPrice: price,
          sellFeeUsd: record.feeUsd ?? 0,
          closeExecutionId: executionId,
          closeReason: "manual"
        });
      } catch (err) {
        console.error(`[kill-bot] applySellToOpenPositions failed for ${record.symbol}:`, err);
      }
    }

    // After snapshot
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

    await notifySlack(`Bot ${bot.name} killed. Liquidation run ${runStatus}.`);
    return { runId, status: runStatus, killed: true as const };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown kill error";
    if (runId) {
      try {
        await finishRun({
          runId,
          runtimeConfigId: bot.runtimeConfigId,
          status: "failure",
          errorState: { message: errorMessage }
        });
      } catch {
        // finishRun itself failed — run stays as "running" in DB
      }
    }
    await notifySlack(`Bot ${bot.name} killed. Liquidation failed: ${errorMessage}`);
    return { runId, status: "failure" as const, killed: true as const };
  }
};
