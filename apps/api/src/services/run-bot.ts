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
  roundToTick,
  netForVenue
} from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  markRuntimeRunFinished,
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
  recordAgentStep,
  type BotSetup
} from "../lib/store.js";
import {
  computeLogicalBalances,
  buildLogicalSnapshot,
  getHeldSymbols,
  computeAfterSnapshot,
  baseAssetFromSymbol
} from "../lib/logical-balances.js";
import {
  runResearchAgent,
  runTraderAgent,
  extractCandidateSymbols,
  DecisionParseError
} from "./pipeline.js";
import { getVenueSymbols } from "./catalog.js";
import { notifySlack } from "./notifier.js";
import { buildTraderPhaseContext, buildResearchPhaseContext } from "./prompt-context.js";
import { validateDecision } from "./validator.js";
import { killBotAndLiquidate } from "./kill-bot.js";
import { describeMaxDrawdownBreach, isMaxDrawdownBreached } from "./drawdown.js";
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

const safeRecordLightStep = async (input: {
  runId: string;
  agentKey: string;
  agentLabel: string;
  inputJson?: unknown;
  outputText?: string | null;
  outputJson?: unknown;
  toolCalls?: unknown;
  modelProvider?: string | null;
  model?: string | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
  error?: string | null;
}) => {
  try {
    await recordAgentStep({
      scopeType: "bot_run",
      scopeId: input.runId,
      agentKey: input.agentKey,
      agentLabel: input.agentLabel,
      inputJson: input.inputJson,
      outputText: input.outputText,
      outputJson: input.outputJson,
      toolCalls: input.toolCalls,
      modelProvider: input.modelProvider,
      model: input.model,
      inputTokens: input.inputTokens,
      outputTokens: input.outputTokens,
      error: input.error,
      status: input.error ? "failure" : "success"
    });
  } catch (error) {
    console.warn("[run-bot] failed to record agent step:", error instanceof Error ? error.message : error);
  }
};

export const runBot = async (bot: BotSetup, opts: { manual?: boolean } = {}) => {
  let runtimeClaimed = false;

  // Atomic claim: every run source uses the same DB lock. Manual runs are
  // allowed before the next scheduled time, but never overlap an active run.
  const claimed = await claimRun(bot.runtimeConfigId, { force: opts.manual === true });
  if (!claimed) {
    return { runId: null, status: "skipped" as const };
  }
  runtimeClaimed = true;

  let runId: string | null = null;

  try {
    // ── 1. Build "before" state ──────────────────────────────────────
    const beforeLedger = await listBotExecutionLedger(bot.id);
    const beforeLogical = computeLogicalBalances(bot.runtimeConfig.budgetUsdt, beforeLedger);
    const initialSymbols = symbolsForPricing(bot.runtimeConfig, getHeldSymbols(beforeLogical, bot.runtimeConfig), []);
    const beforeVenueRaw = await loadVenueContext(
      bot.runtimeConfig,
      initialSymbols.length > 0 ? initialSymbols : [...bot.runtimeConfig.contextSymbols, ...getHeldSymbols(beforeLogical, bot.runtimeConfig)]
    );
    const beforeVenueContext = {
      ...beforeVenueRaw,
      snapshot: buildLogicalSnapshot({
        runtimeConfig: bot.runtimeConfig,
        logical: beforeLogical,
        priceMap: beforeVenueRaw.priceMap
      })
    };

    if (isMaxDrawdownBreached(bot.runtimeConfig, beforeVenueContext.snapshot.totalUsdValue)) {
      const detail = describeMaxDrawdownBreach(bot.runtimeConfig, beforeVenueContext.snapshot.totalUsdValue);
      const killResult = await killBotAndLiquidate(bot, { reason: "max_drawdown", detail });
      return {
        runId: killResult.runId,
        status: killResult.status,
        killed: true as const,
        reason: "max_drawdown" as const
      };
    }

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
    await safeRecordLightStep({
      runId,
      agentKey: "research",
      agentLabel: "Research",
      inputJson: {
        strategy: "research_prompt",
        promptVersionId: bot.promptVersionId
      },
      outputText: researchResult.rawText,
      outputJson: {
        provider: researchResult.provider,
        model: researchResult.model
      },
      modelProvider: researchResult.provider,
      model: researchResult.model
    });

    // ── 3. Prepare Trader context ────────────────────────────────────
    // We still compute candidateSymbols from the research output for logging/debugging
    // (and to help surface "what did the research mention" in the UI). But the trader no
    // longer receives pre-fetched prices — it calls `binance_symbol_lookup` itself.
    const venueSymbols = await getVenueSymbols(bot.runtimeConfig.venue);
    const candidateSymbols = extractCandidateSymbols(researchResult.rawText, venueSymbols);
    const decisionVenueContext = beforeVenueContext;

    const traderCtx = await buildTraderPhaseContext({
      bot,
      venueContext: decisionVenueContext,
      researchRawText: researchResult.rawText,
      candidateSymbols
    });

    // Update run with full prompt context
    const compactContext = {
      ...researchCtx.compactContext,
      trader: traderCtx.compactContext,
      researchCandidateSymbols: candidateSymbols
    };

    const promptSystem = [
      "=== PHASE 1 — RESEARCH (system) ===",
      researchCtx.systemPrompt,
      "",
      "=== PHASE 2 — TRADER (system) ===",
      traderCtx.systemPrompt
    ].join("\n");

    const promptUser = [
      "=== PHASE 1 — RESEARCH (user context) ===",
      researchCtx.userMessage,
      "",
      "=== PHASE 2 — TRADER (user context) ===",
      traderCtx.userMessage
    ].join("\n");

    // Persist combined prompts so the UI can show both phases
    await updateRunPrompts(runId, promptSystem, promptUser);

    // ── 4. Trader Agent (agentic; uses binance_symbol_lookup tool) ───
    const traderResult = await runTraderAgent({
      bot,
      systemPrompt: traderCtx.systemPrompt,
      userMessage: traderCtx.userMessage,
      runId,
      toolContext: { mode: netForVenue(bot.runtimeConfig.venue) }
    });

    await storeTraderOutput(runId, traderResult.rawText);
    await safeRecordLightStep({
      runId,
      agentKey: "trader",
      agentLabel: "Trader",
      inputJson: {
        candidateSymbols,
        traderPromptVersionId: traderCtx.traderPromptVersionId
      },
      outputText: traderResult.rawText,
      outputJson: traderResult.decision,
      toolCalls: traderResult.toolCalls,
      modelProvider: traderResult.provider,
      model: traderResult.model
    });

    // ── 5. Deterministic Validator ───────────────────────────────────
    const validationResult = await validateDecision({
      decision: traderResult.decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: decisionVenueContext
    });
    await safeRecordLightStep({
      runId,
      agentKey: "validator",
      agentLabel: "Validator",
      inputJson: traderResult.decision,
      outputText: validationResult.accepted
        ? "Decision accepted by deterministic validator"
        : `Decision rejected: ${validationResult.issues.join("; ")}`,
      outputJson: validationResult,
      error: validationResult.accepted ? null : validationResult.issues.join("; ")
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
    const executions = bot.runtimeConfig.execution.enabled
      ? await executeOrders({
          runId,
          runtimeConfig: bot.runtimeConfig,
          orders: validationResult.normalizedOrders,
          venueContext: decisionVenueContext
        })
      : [];
    await safeRecordLightStep({
      runId,
      agentKey: "execution",
      agentLabel: "Execution",
      inputJson: {
        normalizedOrders: validationResult.normalizedOrders,
        executionEnabled: bot.runtimeConfig.execution.enabled
      },
      outputText: !bot.runtimeConfig.execution.enabled
        ? "Order placement disabled by runtime execution settings"
        : executions.length > 0
        ? executions.map((execution) => `${execution.side} ${execution.symbol} ${execution.status}`).join(", ")
        : "No executions",
      outputJson: {
        executions
      },
      error: executions.some((execution) => execution.status === "failure")
        ? "At least one execution failed"
        : null
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
        const baseAsset = baseAssetFromSymbol(record.symbol);
        const baseFeeQty =
          baseAsset && record.feeAsset?.toUpperCase() === baseAsset
            ? record.feeAmount ?? 0
            : 0;
        const positionQty = Math.max(0, qty - baseFeeQty);
        if (positionQty <= 0) {
          console.warn(`[run-bot] buy ${record.symbol} filled but net position quantity is ${positionQty}`);
          continue;
        }
        const costBasisUsd = qty * price + feeUsd;
        let createdPositionId: string | null = null;
        try {
          const pos = await openPosition({
            botId: bot.id,
            symbol: record.symbol,
            quantity: positionQty,
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
          const safetyQty = rules ? roundToStep(positionQty, rules.stepSize) : positionQty;
          if (safetyPrice > 0 && safetyQty > 0 && (!rules || safetyQty >= rules.minQty)) {
            try {
              const result = await placeSafetyStopOrder({
                mode: netForVenue(bot.runtimeConfig.venue),
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
      ...getHeldSymbols(afterLogical, bot.runtimeConfig)
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

    if (isMaxDrawdownBreached(bot.runtimeConfig, afterSnapshot.totalUsdValue)) {
      const detail = describeMaxDrawdownBreach(bot.runtimeConfig, afterSnapshot.totalUsdValue);
      const killResult = await killBotAndLiquidate(bot, { reason: "max_drawdown", detail });
      return {
        runId,
        status: runStatus,
        decision: traderResult.decision,
        killed: true as const,
        killRunId: killResult.runId,
        reason: "max_drawdown" as const
      };
    }

    return { runId, status: runStatus, decision: traderResult.decision };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown run error";

    if (runId) {
      if (error instanceof DecisionParseError) {
        await storeTraderOutput(runId, error.rawText);
      }
      await safeRecordLightStep({
        runId,
        agentKey: "run_failure",
        agentLabel: "Run Failure",
        outputText: errorMessage,
        outputJson: { message: errorMessage },
        error: errorMessage
      });
      await finishRun({
        runId,
        runtimeConfigId: bot.runtimeConfigId,
        status: "failure",
        errorState: { message: errorMessage }
      });
    } else if (runtimeClaimed) {
      await markRuntimeRunFinished({
        runtimeConfigId: bot.runtimeConfigId
      });
    }

    await notifySlack(`Run failure for ${bot.name}: ${errorMessage}`);
    throw error;
  }
};
