// module: Bot lifecycle + run/positions/runs/kill routes.
import { Router, type Router as ExpressRouter } from "express";
import {
  ALL_SYMBOLS_TOKEN,
  prePromptConfigSchema,
  runtimeConfigSchema,
  traderConfigSchema
} from "@cosmu/shared";
import {
  createBot,
  getAllEnabledBotSetups,
  getBotSetupById,
  getLLMCallsForRun,
  getRunDetail,
  killBot,
  listActivePositions,
  touchResearchPromptUsage,
  touchTraderPromptUsage,
  updateBotConfig
} from "../lib/store.js";
import { getTickerPricesForSymbols, netForVenue, normalizeSymbol } from "../adapters/binance.js";
import { checkVenueConnection, type VenueId } from "../services/venues.js";
import { notifySlack } from "../services/notifier.js";
import { runBot } from "../services/run-bot.js";
import { killBotAndLiquidate } from "../services/kill-bot.js";

export const botsRouter: ExpressRouter = Router();

const botCreateRuntimeConfigSchema = runtimeConfigSchema.omit({ enabled: true });

const assertVenueConnected = async (venue: VenueId) => {
  const status = await checkVenueConnection(venue, { force: true });
  if (!status.connected) {
    throw new Error(`${status.label} is not connected. ${status.error ?? "Check backend API credentials and permissions."}`);
  }
};

botsRouter.get("/runs/:runId", async (request, response, next) => {
  try {
    const detail = await getRunDetail(request.params.runId);
    if (!detail) {
      response.status(404).json({ error: "Run not found" });
      return;
    }
    response.json(detail);
  } catch (error) {
    next(error);
  }
});

botsRouter.post("/bots/:botId/kill", async (request, response, next) => {
  try {
    const bot = await getBotSetupById(request.params.botId);
    if (!bot) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    if (!bot.runtimeConfig.enabled) {
      response.status(409).json({ error: "Bot is already killed" });
      return;
    }

    const result = await killBotAndLiquidate(bot);
    response.json(result);
  } catch (error) {
    next(error);
  }
});

botsRouter.post("/bots/:botId/run", async (request, response, next) => {
  try {
    const bot = await getBotSetupById(request.params.botId);
    if (!bot) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    if (!bot.runtimeConfig.enabled) {
      response.status(409).json({ error: "Bot is killed. Duplicate this bot to restart from scratch." });
      return;
    }

    const result = await runBot(bot, { manual: true });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

botsRouter.get("/bots/:botId/setup", async (request, response, next) => {
  try {
    const bot = await getBotSetupById(request.params.botId);
    if (!bot) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    response.json(bot);
  } catch (error) {
    next(error);
  }
});

botsRouter.get("/bots/:botId/details", async (request, response, next) => {
  try {
    const { getBotPrePromptContext } = await import("../lib/store.js");
    const details = await getBotPrePromptContext({ botId: request.params.botId, pastTradesLookback: 100 });
    response.json(details);
  } catch (error) {
    next(error);
  }
});

botsRouter.get("/bots/:botId/positions", async (request, response, next) => {
  try {
    const bot = await getBotSetupById(request.params.botId);
    if (!bot) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }
    const positions = await listActivePositions(bot.id);
    if (positions.length === 0) {
      response.json({ positions: [] });
      return;
    }

    let priceMap: Record<string, number> = {};
    try {
      const symbols = positions.map((p) => normalizeSymbol(p.symbol));
      priceMap = await getTickerPricesForSymbols(netForVenue(bot.runtimeConfig.venue), symbols);
    } catch (err) {
      console.warn(`[positions] ticker fetch failed for bot ${bot.id}:`, err instanceof Error ? err.message : err);
    }

    response.json({
      positions: positions.map((p) => {
        const currentPrice = priceMap[normalizeSymbol(p.symbol)] ?? null;
        const pnlPct = currentPrice && p.avgEntryPrice > 0
          ? ((currentPrice - p.avgEntryPrice) / p.avgEntryPrice) * 100
          : null;
        const unrealizedPnlUsd = currentPrice
          ? (currentPrice - p.avgEntryPrice) * p.quantity
          : null;
        return {
          id: p.id,
          symbol: p.symbol,
          quantity: p.quantity,
          avgEntryPrice: p.avgEntryPrice,
          stopLossPrice: p.stopLossPrice,
          takeProfitPrice: p.takeProfitPrice,
          safetyStopPrice: p.safetyStopPrice,
          openedAt: p.openedAt,
          currentPrice,
          pnlPct,
          unrealizedPnlUsd
        };
      })
    });
  } catch (error) {
    next(error);
  }
});

botsRouter.get("/bots/:botId/runs", async (request, response, next) => {
  try {
    const { getBotRuns } = await import("../lib/store.js");
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    const offset = request.query.offset ? Number(request.query.offset) : undefined;
    const includeGuardian = request.query.includeGuardian === "true";
    const result = await getBotRuns(request.params.botId, { limit, offset, includeGuardian });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

botsRouter.post("/bots", async (request, response, next) => {
  try {
    const { name, slug, promptVersionId, modelProfileId, traderModelProfileId, promptConfig, traderConfig, traderPromptVersionId, parentBotId, enabled, runtimeConfig } =
      request.body;
    const parsedRuntimeConfig = botCreateRuntimeConfigSchema.parse(runtimeConfig);
    try {
      await assertVenueConnected(parsedRuntimeConfig.venue);
    } catch (connectionError) {
      response.status(409).json({
        error: connectionError instanceof Error ? connectionError.message : "Selected venue is not connected"
      });
      return;
    }
    const id = await createBot({
      name,
      slug,
      promptVersionId,
      modelProfileId,
      traderModelProfileId: traderModelProfileId ?? null,
      promptConfig: prePromptConfigSchema.parse(promptConfig ?? {}),
      traderConfig: traderConfig === undefined ? undefined : traderConfigSchema.parse(traderConfig),
      traderPromptVersionId: traderPromptVersionId ?? null,
      parentBotId,
      enabled: typeof enabled === "boolean" ? enabled : undefined,
      runtimeConfig: parsedRuntimeConfig
    });

    // Track prompt usage
    if (promptVersionId) void touchResearchPromptUsage(promptVersionId).catch(() => {});
    if (traderPromptVersionId) void touchTraderPromptUsage(traderPromptVersionId).catch(() => {});

    response.json({
      id,
      initialRunQueued: true,
      schedulerEnabled: true
    });

    setImmediate(() => {
      void (async () => {
        try {
          const bot = await getBotSetupById(id);
          if (!bot) {
            console.warn(`[create-bot] initial run skipped; bot ${id} not found`);
            return;
          }
          if (!bot.runtimeConfig.enabled) {
            console.log(`[create-bot] initial run skipped for disabled bot ${id}`);
            return;
          }
          const result = await runBot(bot);
          console.log(`[create-bot] initial run ${result.status} for bot ${id}${result.runId ? ` (${result.runId})` : ""}`);
        } catch (error) {
          console.error(`[create-bot] initial run failed for bot ${id}:`, error);
        }
      })();
    });
  } catch (error) {
    next(error);
  }
});

botsRouter.patch("/bots/:botId", async (request, response, next) => {
  try {
    const current = await getBotSetupById(request.params.botId);
    if (!current) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    const {
      name,
      enabled,
      promptVersionId,
      traderPromptVersionId,
      modelProfileId,
      traderModelProfileId,
      promptConfig,
      traderConfig,
      runtimeConfig,
      venue,
      frequencyMinutes,
      budgetUsdt,
      symbolScope,
      contextSymbols,
      execution
    } = request.body;

    if (enabled !== undefined) {
      response.status(409).json({
        error: "Bots can no longer be enabled/disabled. Use kill mode to stop a bot permanently."
      });
      return;
    }

    const runtimePatchRequested =
      runtimeConfig !== undefined ||
      venue !== undefined ||
      frequencyMinutes !== undefined ||
      budgetUsdt !== undefined ||
      symbolScope !== undefined ||
      contextSymbols !== undefined ||
      execution !== undefined;

    const nextRuntimeConfig = runtimePatchRequested
      ? runtimeConfigSchema.parse({
          ...current.runtimeConfig,
          ...(runtimeConfig ?? {}),
          venue: venue ?? runtimeConfig?.venue ?? current.runtimeConfig.venue,
          frequencyMinutes: frequencyMinutes ?? runtimeConfig?.frequencyMinutes ?? current.runtimeConfig.frequencyMinutes,
          budgetUsdt: budgetUsdt ?? runtimeConfig?.budgetUsdt ?? current.runtimeConfig.budgetUsdt,
          symbolScope: symbolScope ?? runtimeConfig?.symbolScope ?? current.runtimeConfig.symbolScope,
          contextSymbols:
            contextSymbols ??
            runtimeConfig?.contextSymbols ??
            (current.runtimeConfig.symbolScope === "all" ? [ALL_SYMBOLS_TOKEN] : current.runtimeConfig.contextSymbols),
          execution: execution ?? runtimeConfig?.execution ?? current.runtimeConfig.execution
        })
      : undefined;

    if (nextRuntimeConfig?.symbolScope === "all") {
      nextRuntimeConfig.contextSymbols = [ALL_SYMBOLS_TOKEN];
    }

    if (nextRuntimeConfig) {
      try {
        await assertVenueConnected(nextRuntimeConfig.venue);
      } catch (connectionError) {
        response.status(409).json({
          error: connectionError instanceof Error ? connectionError.message : "Selected venue is not connected"
        });
        return;
      }
    }

    await updateBotConfig(request.params.botId, {
      name,
      promptVersionId,
      traderPromptVersionId,
      modelProfileId,
      traderModelProfileId,
      promptConfig: promptConfig === undefined ? undefined : prePromptConfigSchema.parse(promptConfig),
      traderConfig: traderConfig === undefined ? undefined : traderConfigSchema.parse(traderConfig),
      runtimeConfig: nextRuntimeConfig
    });

    if (promptVersionId) void touchResearchPromptUsage(promptVersionId).catch(() => {});
    if (traderPromptVersionId) void touchTraderPromptUsage(traderPromptVersionId).catch(() => {});

    response.json({ ok: true });
  } catch (error) {
    next(error);
  }
});

botsRouter.post("/bots/kill-all", async (_request, response, next) => {
  try {
    const bots = await getAllEnabledBotSetups();
    if (bots.length === 0) {
      response.json({ killed: 0, results: [] });
      return;
    }

    await Promise.all(bots.map((bot) => killBot(bot.id)));
    await notifySlack(`KILL ALL BOTS triggered — liquidating ${bots.length} active bot(s).`);

    const results = [];
    for (const bot of bots) {
      try {
        const result = await killBotAndLiquidate(bot);
        results.push({ botId: bot.id, name: bot.name, ...result });
      } catch (error) {
        results.push({
          botId: bot.id,
          name: bot.name,
          status: "failure" as const,
          killed: true as const,
          error: error instanceof Error ? error.message : "Unknown error"
        });
      }
    }

    response.json({ killed: bots.length, results });
  } catch (error) {
    next(error);
  }
});

botsRouter.get("/runs/:runId/llm-calls", async (request, response, next) => {
  try {
    const calls = await getLLMCallsForRun(request.params.runId);
    response.json({ runId: request.params.runId, calls });
  } catch (error) {
    next(error);
  }
});
