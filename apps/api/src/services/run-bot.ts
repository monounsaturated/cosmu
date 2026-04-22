/**
 * Cosmu v2 Bot Runner
 *
 * Orchestrates: Research Agent → Trader Agent → Validator → Execution
 * Uses the new pipeline, MCP tools, and LLM call logging.
 */

import {
  loadVenueContext,
  executeOrders,
  placeSafetyStopOrder,
  roundToStep,
  roundToTick
} from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  listBotExecutionLedger,
  claimRun,
  recentTradeAlerts,
  storeDecision,
  storeExecutionRecords,
  storeResearchOutput,
  storeTraderOutput,
  updateRunPrompts,
  storePortfolioSnapshot,
  openPosition,
  applySellToOpenPositions,
  updateSafetyStop,
  type BotSetup
} from "../lib/store.js";
import {
  computeLogicalBalances,
  buildLogicalSnapshot,
  getHeldSymbols,
  computeAfterSnapshot
} from "../lib/logical-balances.js";
import {
  runResearchAgent,
  runTraderAgent,
  extractCandidateSymbols,
  DecisionParseError
} from "./pipeline.js";
import { getVenueSymbols } from "./catalog.js";
import { notifySlack } from "./notifier.js";
import { buildFormatterPhaseContext, buildResearchPhaseContext } from "./prompt-context.js";
import { validateDecision } from "./validator.js";
import { ALL_SYMBOLS_TOKEN, type RuntimeConfig } from "@cosmu/shared";

const normalizePricingSymbol = (value: string) => value.replace(/[^A-Z0-9]/gi, "").toUpperCase();

const symbolsForPricing = (
  runtime: RuntimeConfig,
  held: string[],
  researchCandidates: string[]
): string[] => {
  const set = new Set<string>();
  const add = (raw: string) => {
    const n = normalizePricingSymbol(raw);
    if (!n || n === "USDTUSDT" || n === "USDCUSDC") return;
    set.add(n);
  };
  for (const h of held) add(h);
  for (const c of researchCandidates) {
    const n = normalizePricingSymbol(c);
    if (n && (n.endsWith("USDT") || n.endsWith("USDC"))) set.add(n);
  }
  for (const s of runtime.contextSymbols) {
    if (s === ALL_SYMBOLS_TOKEN) continue;
    add(s);
  }
  return Array.from(set);
};

const summarizeTrades = async (runId: string) => {
  const trades = await recentTradeAlerts(runId);
  if (trades.length === 0) return "No executions";
  return trades.map((trade) => `${trade.side} ${trade.symbol} (${trade.status})`).join(", ");
};

export const runBot = async (bot: BotSetup, opts: { manual?: boolean } = {}) => {
  // Atomic claim: if another tick/source already started this cycle, bail out
  // silently. Protects against double-firing from overlapping scheduler sources
  // (internal 15s loop + external /internal/scheduler/tick cron).
  // Manual triggers (Run Now button) bypass the claim to always fire.
  if (!opts.manual) {
    const claimed = await claimRun(bot.runtimeConfigId);
    if (!claimed) {
      return { runId: null, status: "skipped" as const };
    }
  }

  let runId: string | null = null;

  try {
    // ── 1. Build "before" state ──────────────────────────────────────
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

    // ── 2. Research Agent ────────────────────────────────────────────
    const researchCtx = await buildResearchPhaseContext({
      bot,
      venueContext: beforeVenueContext
    });

    // Create run early so we can log LLM calls against it
    const compactContextPlaceholder = {
      ...researchCtx.compactContext,
      phase: "initializing"
    };

    runId = await createRun({
      botId: bot.id,
      promptVersionId: bot.promptVersionId,
      modelProfileId: bot.modelProfileId,
      runtimeConfig: bot.runtimeConfig,
      compactContext: compactContextPlaceholder,
      promptSystem: researchCtx.systemPrompt,
      promptUser: researchCtx.userMessage
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    const researchResult = await runResearchAgent({
      bot,
      systemPrompt: researchCtx.systemPrompt,
      userMessage: researchCtx.userMessage,
      runId
    });

    await storeResearchOutput(runId, researchResult.rawText);

    // ── 3. Prepare Trader context ────────────────────────────────────
    // We still compute candidateSymbols from the research output for logging/debugging
    // (and to help surface "what did the research mention" in the UI). But the trader no
    // longer receives pre-fetched prices — it calls `binance_symbol_lookup` itself.
    const venueSymbols = await getVenueSymbols("binance");
    const candidateSymbols = extractCandidateSymbols(researchResult.rawText, venueSymbols);
    const decisionVenueContext = beforeVenueContext;

    const formatterCtx = await buildFormatterPhaseContext({
      bot,
      venueContext: decisionVenueContext,
      researchRawText: researchResult.rawText,
      candidateSymbols
    });

    // Update run with full prompt context
    const compactContext = {
      ...researchCtx.compactContext,
      formatter: formatterCtx.compactContext,
      researchCandidateSymbols: candidateSymbols
    };

    const promptSystem = [
      "=== PHASE 1 — RESEARCH (system) ===",
      researchCtx.systemPrompt,
      "",
      "=== PHASE 2 — TRADER (system) ===",
      formatterCtx.systemPrompt
    ].join("\n");

    const promptUser = [
      "=== PHASE 1 — RESEARCH (user context) ===",
      researchCtx.userMessage,
      "",
      "=== PHASE 2 — TRADER (user context) ===",
      formatterCtx.userMessage
    ].join("\n");

    // Persist combined prompts so the UI can show both phases
    await updateRunPrompts(runId, promptSystem, promptUser);

    // ── 4. Trader Agent (agentic; uses binance_symbol_lookup tool) ───
    const traderResult = await runTraderAgent({
      bot,
      systemPrompt: formatterCtx.systemPrompt,
      userMessage: formatterCtx.userMessage,
      runId,
      toolContext: { mode: bot.runtimeConfig.mode }
    });

    await storeTraderOutput(runId, traderResult.rawText);

    // ── 5. Deterministic Validator ───────────────────────────────────
    const validationResult = await validateDecision({
      decision: traderResult.decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: decisionVenueContext
    });

    await storeDecision({
      runId,
      decision: traderResult.decision,
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
      return { runId, status: "failure" as const, decision: traderResult.decision };
    }

    // ── 6. Execution ─────────────────────────────────────────────────
    const executions = await executeOrders({
      runId,
      runtimeConfig: bot.runtimeConfig,
      orders: validationResult.normalizedOrders,
      venueContext: decisionVenueContext
    });

    const storedExecutions = await storeExecutionRecords(runId, executions);

    // ── 6b. Update per-bot position ledger ───────────────────────────
    // Buy with SL/TP and a real fill → open a position row.
    // Sell with a real fill → FIFO-close open positions for that symbol.
    for (const { id: executionId, record } of storedExecutions) {
      if (record.status !== "success") continue;
      const qty = record.executedQuantity ?? 0;
      const price = record.averageFillPrice ?? record.requestedLimitPrice ?? null;
      if (qty <= 0 || !price) continue;

      if (record.side === "buy" && record.stopLossPrice && record.takeProfitPrice) {
        const feeUsd = record.feeUsd ?? 0;
        const costBasisUsd = qty * price + feeUsd;
        let createdPositionId: string | null = null;
        try {
          const pos = await openPosition({
            botId: bot.id,
            symbol: record.symbol,
            quantity: qty,
            avgEntryPrice: price,
            costBasisUsd,
            stopLossPrice: record.stopLossPrice,
            takeProfitPrice: record.takeProfitPrice,
            buyExecutionId: executionId
          });
          createdPositionId = pos.id;
        } catch (err) {
          console.error(`[run-bot] openPosition failed for ${record.symbol}:`, err);
        }

        // Place Binance "safety stop" — a wider STOP_LOSS that protects us if
        // the app is down when the app-SL triggers. Guardian normally fires
        // first and cancels this order before selling.
        if (createdPositionId) {
          const safetyPct = 0.10; // 10% wider than app SL
          const rules = decisionVenueContext.symbolRules[record.symbol];
          const rawSafety = record.stopLossPrice * (1 - safetyPct);
          const safetyPrice = rules ? roundToTick(rawSafety, rules.tickSize) : rawSafety;
          const safetyQty = rules ? roundToStep(qty, rules.stepSize) : qty;
          if (safetyPrice > 0 && safetyQty > 0 && (!rules || safetyQty >= rules.minQty)) {
            try {
              const result = await placeSafetyStopOrder({
                mode: bot.runtimeConfig.mode,
                symbol: record.symbol,
                quantity: safetyQty,
                stopPrice: safetyPrice,
                clientOrderId: `safety-${createdPositionId.replace(/-/g, "").slice(0, 12)}-${Date.now().toString(36)}`,
                orderTypes: rules?.orderTypes,
                tickSize: rules?.tickSize
              });
              await updateSafetyStop(createdPositionId, safetyPrice, result.orderId);
              console.log(`[run-bot] safety stop placed for ${record.symbol} (${result.type}) @ ${safetyPrice}`);
            } catch (err) {
              console.error(`[run-bot] safety stop placement failed for ${record.symbol}:`, err instanceof Error ? err.message : err);
            }
          } else {
            console.warn(`[run-bot] safety stop skipped for ${record.symbol}: price=${safetyPrice} qty=${safetyQty} minQty=${rules?.minQty}`);
          }
        }
      } else if (record.side === "sell") {
        try {
          const result = await applySellToOpenPositions({
            botId: bot.id,
            symbol: record.symbol,
            sellQuantity: qty,
            sellPrice: price,
            sellFeeUsd: record.feeUsd ?? 0,
            closeExecutionId: executionId,
            closeReason: "run_sell"
          });
          if (result.unmatchedQuantity > 1e-8) {
            console.warn(
              `[run-bot] sell ${record.symbol} left ${result.unmatchedQuantity} unmatched (no open position)`
            );
          }
        } catch (err) {
          console.error(`[run-bot] applySellToOpenPositions failed for ${record.symbol}:`, err);
        }
      }
    }

    // ── 7. After snapshot ────────────────────────────────────────────
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

    return { runId, status: runStatus, decision: traderResult.decision };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown run error";

    if (runId) {
      if (error instanceof DecisionParseError) {
        await storeTraderOutput(runId, error.rawText);
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
