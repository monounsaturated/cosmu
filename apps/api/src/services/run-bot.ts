/**
 * Cosmu v2 Bot Runner
 *
 * Orchestrates: Research Agent → Trader Agent → Validator → Execution
 * Uses the new pipeline, MCP tools, and LLM call logging.
 */

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
  updateRunPrompts,
  storePortfolioSnapshot,
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
  for (const h of held) {
    const n = normalizePricingSymbol(h);
    if (n && n !== "USDTUSDT") set.add(n);
  }
  for (const c of researchCandidates) {
    const n = normalizePricingSymbol(c);
    if (n && n.endsWith("USDT") && n !== "USDTUSDT") set.add(n);
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
  if (trades.length === 0) return "No executions";
  return trades.map((trade) => `${trade.side} ${trade.symbol} (${trade.status})`).join(", ");
};

export const runBot = async (bot: BotSetup) => {
  await markRunStarted(bot.runtimeConfigId);

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

    // ── 3. Prepare Trader context ────────────────────────────────────
    const venueSymbols = await getVenueSymbols("binance");
    const candidateSymbols = extractCandidateSymbols(researchResult.rawText, venueSymbols);

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
      researchRawText: researchResult.rawText,
      candidateSymbols,
      priceSymbolFilter
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

    // ── 4. Trader Agent ──────────────────────────────────────────────
    const traderResult = await runTraderAgent({
      bot,
      systemPrompt: formatterCtx.systemPrompt,
      userMessage: formatterCtx.userMessage,
      runId
    });

    await storeRawModelOutput(
      runId,
      JSON.stringify(
        {
          phase1Research: researchResult.rawText,
          phase2Trader: traderResult.rawText
        },
        null,
        2
      )
    );

    // ── 5. Deterministic Validator ───────────────────────────────────
    const validationResult = await validateDecision({
      decision: traderResult.decision,
      runtimeConfig: bot.runtimeConfig,
      venueContext: decisionVenueContext
    });

    await storeDecision({
      runId,
      rawModelOutput: traderResult.rawText,
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

    await storeExecutionRecords(runId, executions);

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
        await storeRawModelOutput(runId, error.rawText);
      } else {
        await storeRawModelOutput(
          runId,
          JSON.stringify({ providerError: errorMessage, at: new Date().toISOString() }, null, 2)
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
