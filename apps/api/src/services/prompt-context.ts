import type { VenueContext } from "../adapters/binance.js";
import { getBotPrePromptContext, type BotSetup } from "../lib/store.js";

const PRESET_INSTRUCTIONS: Record<string, string> = {
  minimal: "Focus on high-conviction decisions. Use only the most relevant facts from the structured context.",
  performance:
    "Optimize for durable net performance after fees. Prefer disciplined decisions over unnecessary trading activity.",
  competitive:
    "Aim to outperform the other bots on risk-adjusted net performance, while keeping turnover and fees under control.",
  "full-context":
    "Use the full structured context carefully. Synthesize portfolio state, performance, rankings, and trade history before acting."
};

type BuildPromptContextInput = {
  bot: BotSetup;
  venueContext: VenueContext;
};

const buildBaseRuntimeContext = (bot: BotSetup, venueContext: VenueContext) => ({
  bot: {
    id: bot.id,
    botNumber: bot.botNumber,
    name: bot.name,
    slug: bot.slug
  },
  venue: bot.runtimeConfig.venue,
  mode: bot.runtimeConfig.mode,
  assetClass: bot.runtimeConfig.assetClass,
  promptVersion: bot.promptVersionLabel,
  modelProfile: bot.modelProfileName,
  executionConstraints: {
    maxOrdersPerRun: bot.runtimeConfig.execution.maxOrdersPerRun,
    maxNotionalPerOrderUsd: bot.runtimeConfig.execution.maxNotionalPerOrderUsd,
    minCashReserveUsd: bot.runtimeConfig.execution.minCashReserveUsd,
    allowMarketOrders: bot.runtimeConfig.execution.allowMarketOrders,
    allowLimitOrders: bot.runtimeConfig.execution.allowLimitOrders
  },
  wallet: venueContext.snapshot.balances,
  prices: venueContext.snapshot.prices
});

export const buildPromptContext = async ({ bot, venueContext }: BuildPromptContextInput) => {
  const runtimeContext = buildBaseRuntimeContext(bot, venueContext);
  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: bot.promptConfig.modules.pastTradesLookback
  });

  const prePromptModules: Record<string, unknown> = {};

  if (bot.promptConfig.modules.includeCurrentPositions) {
    prePromptModules.currentPositions = {
      balances: venueContext.snapshot.balances,
      prices: venueContext.snapshot.prices
    };
  }

  if (bot.promptConfig.modules.includeWalletOverview) {
    prePromptModules.walletOverview = {
      startedPortfolioUsd: historyContext.performance?.firstPortfolioUsd ?? null,
      currentPortfolioUsd: historyContext.performance?.currentPortfolioUsd ?? venueContext.snapshot.totalUsdValue,
      totalUsdValueNow: venueContext.snapshot.totalUsdValue
    };
  }

  if (bot.promptConfig.modules.includePerformanceStats) {
    prePromptModules.performanceStats = historyContext.performance;
  }

  if (bot.promptConfig.modules.includePastTrades) {
    prePromptModules.pastTrades = historyContext.pastTrades;
  }

  if (bot.promptConfig.modules.includeBotRanking) {
    prePromptModules.botRanking = historyContext.ranking.slice(0, 10);
  }

  const activeModules = Object.keys(prePromptModules);

  const systemPrompt = [
    "You are the research decision engine for one autonomous spot trading bot.",
    PRESET_INSTRUCTIONS[bot.promptConfig.preset] ?? PRESET_INSTRUCTIONS.minimal,
    "You will receive a structured JSON payload with two top-level keys: runtimeContext and prePromptModules.",
    activeModules.length > 0
      ? `Active structured modules: ${activeModules.join(", ")}. Treat them as factual context.`
      : "No optional structured modules are active for this bot.",
    "Return only valid JSON matching the response schema.",
    bot.promptBody
  ].join("\n\n");

  return {
    systemPrompt,
    compactContext: {
      runtimeContext,
      prePromptModules
    }
  };
};
