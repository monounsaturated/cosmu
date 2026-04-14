import { loadVenueContext, executeOrders } from "../adapters/binance.js";
import {
  createRun,
  finishRun,
  markRunStarted,
  recentTradeAlerts,
  storeDecision,
  storeExecutionRecords,
  storePortfolioSnapshot,
  type BotSetup
} from "../lib/store.js";
import { requestDecision } from "../providers/xai.js";
import { notifySlack } from "./notifier.js";
import { buildPromptContext } from "./prompt-context.js";
import { validateDecision } from "./validator.js";

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

export const runBot = async (bot: BotSetup) => {
  await markRunStarted(bot.runtimeConfigId);

  let runId: string | null = null;

  try {
    const beforeVenueContext = await loadVenueContext(bot.runtimeConfig, bot.runtimeConfig.contextSymbols);
    const { systemPrompt, userMessage, compactContext } = await buildPromptContext({
      bot,
      venueContext: beforeVenueContext
    });

    runId = await createRun({
      botId: bot.id,
      promptVersionId: bot.promptVersionId,
      modelProfileId: bot.modelProfileId,
      runtimeConfig: bot.runtimeConfig,
      compactContext
    });

    await storePortfolioSnapshot(runId, "before", beforeVenueContext.snapshot);

    const { rawText, decision } = await getDecisionWithRetry(bot, systemPrompt, userMessage);
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

    const afterVenueContext = await loadVenueContext(bot.runtimeConfig, bot.runtimeConfig.contextSymbols);
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
