import { executeOrders, loadVenueContext, cancelAllOpenOrdersForSymbol, getAccountBalance } from "../adapters/binance.js";
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
import {
  computeLogicalBalances,
  buildLogicalSnapshot,
  getHeldSymbols,
  computeAfterSnapshot,
  baseAssetFromSymbol
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
 * Build sell orders from logical balances — only assets above dust threshold.
 */
const buildSellOrdersFromLogical = (logical: ReturnType<typeof computeLogicalBalances>) =>
  Object.entries(logical.assets)
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

/**
 * Build sell orders from actual exchange balances for assets this bot logically holds.
 * Used as a fallback when logical-balance sells fail (e.g. due to lot-size rounding
 * or locked balances). Sells the real free balance, capped to the bot's logical qty.
 */
const buildSellOrdersFromExchangeBalance = (
  exchangeBalances: { asset: string; free: number }[],
  logicalAssets: Record<string, number>
) => {
  const orders: TradingDecision["orders"] = [];
  const exchangeMap = new Map(exchangeBalances.map((b) => [b.asset.toUpperCase(), b.free]));

  for (const [asset, logicalQty] of Object.entries(logicalAssets)) {
    if (logicalQty <= 1e-8) continue;
    const exchangeFree = exchangeMap.get(asset.toUpperCase()) ?? 0;
    if (exchangeFree <= 1e-8) continue;
    // Sell whichever is smaller: what the bot logically owns or what the exchange has free
    const qty = Math.min(logicalQty, exchangeFree);
    orders.push({
      symbol: `${asset}USDT`,
      side: "sell",
      type: "market",
      quantity: qty,
      limitPrice: null,
      stopLossPrice: null,
      takeProfitPrice: null,
      rationale: "Kill mode liquidation (retry with exchange balance)"
    });
  }

  return orders;
};

/**
 * Kill a bot and attempt to liquidate its positions.
 *
 * The bot is disabled FIRST so the scheduler can never pick it up again.
 * Liquidation is best-effort — if it fails the bot is still killed.
 * This function never throws; it always returns a result object.
 */
export const killBotAndLiquidate = async (bot: BotSetup) => {
  // ── Step 1: disable the bot immediately ──────────────────────────────
  await killBot(bot.id);
  await markRunStarted(bot.runtimeConfigId);

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
    await wait(1000);

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
    const sellOrders = buildSellOrdersFromLogical(beforeLogical);

    const decision = buildKillDecision(sellOrders);
    const validationResult = await validateDecision({
      decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: freshVenueContext
    });

    await storeDecision({
      runId,
      rawModelOutput: JSON.stringify(decision),
      decision,
      validationResult
    });

    // In kill mode: execute whatever orders passed validation, even if some failed.
    // Don't abort the entire kill because one symbol is untradable.
    const ordersToExecute = validationResult.normalizedOrders;

    if (validationResult.issues.length > 0) {
      console.warn(`kill-bot: validation issues (executing ${ordersToExecute.length} valid orders anyway):`, validationResult.issues);
    }

    let allExecutions: Awaited<ReturnType<typeof executeOrders>> = [];

    if (ordersToExecute.length > 0) {
      const executions = await executeOrders({
        runId,
        runtimeConfig: bot.runtimeConfig,
        orders: ordersToExecute,
        venueContext: freshVenueContext
      });
      allExecutions.push(...executions);
    }

    // ── Step 3: retry failed sells with fresh exchange balance ─────────
    const failedSymbols = new Set(
      allExecutions
        .filter((e) => e.status === "uncertain")
        .map((e) => e.symbol)
    );

    if (failedSymbols.size > 0) {
      console.warn(`kill-bot: ${failedSymbols.size} sells failed, retrying with fresh exchange balance:`, [...failedSymbols]);
      await wait(1000);

      // Get actual exchange balances and rebuild venue context
      const retryVenueRaw = await loadVenueContext(bot.runtimeConfig, [
        ...bot.runtimeConfig.contextSymbols,
        ...heldSymbols
      ]);
      const exchangeAccount = await getAccountBalance(bot.runtimeConfig.mode);
      const retryOrders = buildSellOrdersFromExchangeBalance(
        exchangeAccount.balances,
        // Only retry the ones that failed
        Object.fromEntries(
          Object.entries(beforeLogical.assets).filter(([asset]) =>
            failedSymbols.has(`${asset}USDT`)
          )
        )
      );

      if (retryOrders.length > 0) {
        const retryDecision = buildKillDecision(retryOrders);
        const retryVenueContext = {
          ...retryVenueRaw,
          // Use real exchange snapshot for retry validation so balance check matches reality
          snapshot: retryVenueRaw.snapshot
        };
        const retryValidation = await validateDecision({
          decision: retryDecision,
          runtimeConfig: bot.runtimeConfig,
          venueContext: retryVenueContext
        });

        if (retryValidation.normalizedOrders.length > 0) {
          const retryExecutions = await executeOrders({
            runId,
            runtimeConfig: bot.runtimeConfig,
            orders: retryValidation.normalizedOrders,
            venueContext: retryVenueContext
          });
          allExecutions.push(...retryExecutions);
        }
      }
    }

    // Also handle orders that failed validation entirely (not even attempted)
    const attemptedSymbols = new Set(allExecutions.map((e) => e.symbol));
    const neverAttempted = sellOrders.filter((o) => !attemptedSymbols.has(o.symbol.replace(/[^A-Z0-9]/gi, "").toUpperCase()));

    if (neverAttempted.length > 0) {
      console.warn(`kill-bot: ${neverAttempted.length} orders never attempted, retrying with exchange balance:`, neverAttempted.map((o) => o.symbol));
      const retryVenueRaw2 = await loadVenueContext(bot.runtimeConfig, [
        ...bot.runtimeConfig.contextSymbols,
        ...heldSymbols
      ]);
      const exchangeAccount2 = await getAccountBalance(bot.runtimeConfig.mode);
      const retryOrders2 = buildSellOrdersFromExchangeBalance(
        exchangeAccount2.balances,
        Object.fromEntries(
          neverAttempted.map((o) => {
            const asset = baseAssetFromSymbol(o.symbol);
            return [asset ?? "", o.quantity];
          }).filter(([asset]) => (asset as string).length > 0)
        )
      );

      if (retryOrders2.length > 0) {
        const retryDecision2 = buildKillDecision(retryOrders2);
        const retryVenueContext2 = {
          ...retryVenueRaw2,
          snapshot: retryVenueRaw2.snapshot
        };
        const retryValidation2 = await validateDecision({
          decision: retryDecision2,
          runtimeConfig: bot.runtimeConfig,
          venueContext: retryVenueContext2
        });

        if (retryValidation2.normalizedOrders.length > 0) {
          const retryExecutions2 = await executeOrders({
            runId,
            runtimeConfig: bot.runtimeConfig,
            orders: retryValidation2.normalizedOrders,
            venueContext: retryVenueContext2
          });
          allExecutions.push(...retryExecutions2);
        }
      }
    }

    await storeExecutionRecords(runId, allExecutions);

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
    const totalFeeUsd = allExecutions.reduce((sum, execution) => sum + (execution.feeUsd ?? 0), 0);
    const afterSnapshot = computeAfterSnapshot({
      beforeSnapshot: beforeVenueContext.snapshot,
      afterSnapshot: afterVenueContext.snapshot,
      totalFeeUsd
    });

    await storePortfolioSnapshot(runId, "after", afterSnapshot);

    const hasUncertain = allExecutions.some((execution) => execution.status === "uncertain");
    const allSuccess = allExecutions.length > 0 && allExecutions.every((e) => e.status === "success");
    const runStatus = allSuccess ? "success" : hasUncertain ? "uncertain" : (allExecutions.length === 0 ? "failure" : "success");

    await finishRun({
      runId,
      runtimeConfigId: bot.runtimeConfigId,
      status: runStatus,
      errorState: hasUncertain
        ? { message: "At least one liquidation execution is uncertain", issues: validationResult.issues }
        : validationResult.issues.length > 0
          ? { message: "Some orders had validation issues", issues: validationResult.issues }
          : null
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
