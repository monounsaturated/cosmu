import cors from "cors";
import express from "express";
import { env } from "./env.js";
import { sql } from "./db.js";
import {
  ALL_SYMBOLS_TOKEN,
  prePromptConfigSchema,
  runtimeConfigSchema,
  traderConfigSchema
} from "@cosmu/shared";
import {
  addPromptVersion,
  createBot,
  createModelProfile,
  createPrompt,
  getBotSetupById,
  getDueBots,
  getAllEnabledBotSetups,
  getRunDetail,
  getPromptVersionBody,
  listModelProfiles,
  listPrompts,
  updateBotConfig,
  getActiveFormatterPrompt,
  getAllActiveFormatterPrompts,
  createFormatterPromptVersion,
  listFormatterPromptVersions,
  getLLMCallsForRun,
  listTraderPrompts,
  createTraderPrompt,
  touchResearchPromptUsage,
  touchTraderPromptUsage,
  listActivePositions,
  getAppSettings,
  setAppSettings
} from "./lib/store.js";
import { getDashboard } from "./services/dashboard.js";
import { buildCorsOptions, corsDiagnostics } from "./cors-options.js";
import { listXaiModels } from "./providers/xai.js";
import { listNousModels } from "./providers/nous.js";
import {
  BOOTSTRAP_ANTHROPIC_PROFILES,
  BOOTSTRAP_GOOGLE_PROFILES,
  BOOTSTRAP_HUGGINGFACE_PROFILES,
  BOOTSTRAP_MISTRAL_PROFILES,
  BOOTSTRAP_OPENAI_PROFILES,
  BOOTSTRAP_NOUS_PROFILES,
  BOOTSTRAP_XAI_PROFILES,
  SUPPORTED_MODEL_PROVIDERS,
  bootstrapModelProfiles,
  modelProviderLabel,
  getVenueSymbols,
  syncProviderModels
} from "./services/catalog.js";
import { getAccountBalance, getTickerPricesForSymbols, normalizeSymbol } from "./adapters/binance.js";
import { notifySlack } from "./services/notifier.js";
import { runBot } from "./services/run-bot.js";
import { killBotAndLiquidate } from "./services/kill-bot.js";
import { startGuardian } from "./services/guardian.js";
import { listTools } from "./mcp/index.js";
import { agentsRouter } from "./routes/agents.js";
import { researchRouter } from "./routes/research.js";
import { signalsRouter } from "./routes/signals.js";
import { tradingAgentsRouter } from "./routes/trading-agents.js";

const app = express();
const botCreateRuntimeConfigSchema = runtimeConfigSchema.omit({ enabled: true });
const ALWAYS_KEEP_XAI_MODEL_IDS = new Set(["grok-4.3"]);

const corsOptions = buildCorsOptions();
app.use(corsOptions ? cors(corsOptions) : cors());
app.use(express.json());

app.use((request, response, next) => {
  if (request.path === "/health") {
    return next();
  }

  const apiKey = request.headers["x-api-key"];
  if (apiKey !== env.API_SECRET_KEY) {
    response.status(401).json({ error: "Unauthorized" });
    return;
  }

  next();
});

app.use(agentsRouter);
app.use(researchRouter);
app.use(signalsRouter);
app.use(tradingAgentsRouter);

app.get("/health", async (_request, response) => {
  response.json({
    ok: true,
    mode: "runtime"
  });
});

app.get("/internal/diagnostics", async (_request, response) => {
  const result: Record<string, unknown> = { checkedAt: new Date().toISOString() };

  try {
    const [r] = await sql<{ count: string }[]>`select count(*)::text as count from model_profiles`;
    result.modelsInDb = Number(r?.count ?? 0);
  } catch (e) { result.modelsDbError = String(e); }

  try {
    const [r] = await sql<{ count: string }[]>`select count(*)::text as count from venue_symbol_catalog where is_active = true`;
    result.symbolsInDb = Number(r?.count ?? 0);
  } catch (e) { result.symbolsDbError = String(e); }

  try {
    const [r] = await sql<{ count: string }[]>`select count(*)::text as count from research_prompts`;
    result.promptsInDb = Number(r?.count ?? 0);
  } catch (e) { result.promptsDbError = String(e); }

  try {
    if (env.XAI_API_KEY) {
      const xaiRes = await fetch("https://api.x.ai/v1/models", {
        headers: { Authorization: `Bearer ${env.XAI_API_KEY}` },
        signal: AbortSignal.timeout(5000)
      });
      result.xaiApi = xaiRes.ok ? `ok (${xaiRes.status})` : `error (${xaiRes.status})`;
    } else {
      result.xaiApi = "missing XAI_API_KEY";
    }
  } catch (e) { result.xaiApi = `unreachable: ${String(e)}`; }

  try {
    if (env.NOUS_API_KEY) {
      const models = await listNousModels();
      result.nousApi = `ok (${models.length} models)`;
    } else {
      result.nousApi = "missing NOUS_API_KEY";
    }
  } catch (e) { result.nousApi = `unreachable: ${String(e)}`; }

  result.modelProviderKeys = {
    xai: Boolean(env.XAI_API_KEY),
    openai: Boolean(env.OPENAI_API_KEY),
    anthropic: Boolean(env.ANTHROPIC_API_KEY),
    google: Boolean(env.GOOGLE_API_KEY),
    mistral: Boolean(env.MISTRAL_API_KEY),
    huggingface: Boolean(env.HUGGINGFACE_API_KEY),
    nous: Boolean(env.NOUS_API_KEY)
  };

  result.tradingAccountKeys = {
    binanceLive: Boolean(env.BINANCE_API_KEY && env.BINANCE_API_SECRET),
    binanceTestnet: Boolean(env.BINANCE_TESTNET_API_KEY && env.BINANCE_TESTNET_API_SECRET)
  };

  try {
    const binRes = await fetch("https://api.binance.com/api/v3/ping", {
      signal: AbortSignal.timeout(5000)
    });
    result.binanceApi = binRes.ok ? `ok (${binRes.status})` : `error (${binRes.status})`;
  } catch (e) { result.binanceApi = `unreachable: ${String(e)}`; }

  result.cors = corsDiagnostics();
  result.scheduler = getSchedulerStatus();

  response.json(result);
});

app.get("/internal/qa/status", async (_request, response) => {
  response.json({
    ok: true,
    runtime: {
      port: env.API_PORT,
      corsOriginMode:
        env.CORS_ALLOW_ANY_ORIGIN === "true"
          ? "any"
          : "whitelist"
    },
    cors: corsDiagnostics(),
    envReadiness: {
      database: Boolean(env.DATABASE_URL),
      apiSecretConfigured: env.API_SECRET_KEY.length >= 32,
      xaiConfigured: Boolean(env.XAI_API_KEY),
      nousConfigured: Boolean(env.NOUS_API_KEY),
      binanceLiveConfigured: Boolean(env.BINANCE_API_KEY && env.BINANCE_API_SECRET),
      binanceTestnetConfigured: Boolean(
        (env.BINANCE_TESTNET_API_KEY && env.BINANCE_TESTNET_API_SECRET)
          || (env.BINANCE_API_KEY && env.BINANCE_API_SECRET)
      ),
      slackConfigured: Boolean(env.SLACK_WEBHOOK_URL),
      webBaseUrlConfigured: Boolean(env.WEB_BASE_URL)
    },
    scheduler: getSchedulerStatus()
  });
});

app.get("/next-numbers", async (_request, response, next) => {
  try {
    const [botRow] = await sql<{ next: number }[]>`select coalesce(max(bot_number), 0) + 1 as next from bots`;
    const [promptRow] = await sql<{ next: number }[]>`select coalesce(count(*), 0) + 1 as next from research_prompts`;
    const [traderRow] = await sql<{ next: number }[]>`select coalesce(max(prompt_number), 0) + 1 as next from trader_prompts`;
    response.json({
      nextBotNumber: botRow.next,
      nextResearchPromptNumber: promptRow.next,
      nextTraderPromptNumber: traderRow.next
    });
  } catch (error) {
    next(error);
  }
});

app.get("/dashboard", async (_request, response, next) => {
  try {
    response.json(await getDashboard());
  } catch (error) {
    next(error);
  }
});

app.get("/settings/formatter-prompt", async (_request, response, next) => {
  try {
    response.json({ formatterPrompts: await getAllActiveFormatterPrompts() });
  } catch (error) {
    next(error);
  }
});

app.get("/settings/app", async (_request, response, next) => {
  try {
    response.json(await getAppSettings());
  } catch (error) {
    next(error);
  }
});

app.put("/settings/app", async (request, response, next) => {
  try {
    response.json(await setAppSettings(request.body));
  } catch (error) {
    next(error);
  }
});

app.put("/settings/formatter-prompt", async (request, response, next) => {
  try {
    const body = request.body as { formatterPrompts?: unknown };
    const raw = body?.formatterPrompts;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      response.status(400).json({ error: "formatterPrompts object required" });
      return;
    }
    const o = raw as Record<string, unknown>;
    if (typeof o.binance !== "string" || typeof o["binance-testnet"] !== "string") {
      response.status(400).json({
        error: "formatterPrompts must include string fields binance and binance-testnet"
      });
      return;
    }
    if (o.binance.length > 12000 || o["binance-testnet"].length > 12000) {
      response.status(400).json({ error: "Each formatter prompt may be at most 12000 characters" });
      return;
    }
    if (o.binance.trim().length > 0) {
      await createFormatterPromptVersion("binance", o.binance.trim());
    }
    if (o["binance-testnet"].trim().length > 0) {
      await createFormatterPromptVersion("binance-testnet", o["binance-testnet"].trim());
    }
    response.json({ ok: true, formatterPrompts: await getAllActiveFormatterPrompts() });
  } catch (error) {
    next(error);
  }
});

app.get("/settings/formatter-prompt/:venue/versions", async (request, response, next) => {
  try {
    const venue = request.params.venue;
    if (venue !== "binance" && venue !== "binance-testnet") {
      response.status(404).json({ error: "Venue not found" });
      return;
    }
    const versions = await listFormatterPromptVersions(venue);
    response.json({ venue, versions });
  } catch (error) {
    next(error);
  }
});

app.get("/runs/:runId", async (request, response, next) => {
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

app.post("/bots/:botId/kill", async (request, response, next) => {
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

app.post("/bots/:botId/run", async (request, response, next) => {
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

app.get("/bots/:botId/setup", async (request, response, next) => {
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

app.get("/bots/:botId/details", async (request, response, next) => {
  try {
    const { getBotPrePromptContext } = await import("./lib/store.js");
    const details = await getBotPrePromptContext({ botId: request.params.botId, pastTradesLookback: 100 });
    response.json(details);
  } catch (error) {
    next(error);
  }
});

app.get("/bots/:botId/positions", async (request, response, next) => {
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
      priceMap = await getTickerPricesForSymbols(bot.runtimeConfig.mode, symbols);
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

app.get("/bots/:botId/runs", async (request, response, next) => {
  try {
    const { getBotRuns } = await import("./lib/store.js");
    const limit = request.query.limit ? Number(request.query.limit) : undefined;
    const offset = request.query.offset ? Number(request.query.offset) : undefined;
    const includeGuardian = request.query.includeGuardian === "true";
    const result = await getBotRuns(request.params.botId, { limit, offset, includeGuardian });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

app.post("/internal/scheduler/tick", async (_request, response, next) => {
  try {
    response.json(await runSchedulerTick("manual"));
  } catch (error) {
    next(error);
  }
});

app.get("/prompts", async (_request, response, next) => {
  try {
    response.json(await listPrompts());
  } catch (error) {
    next(error);
  }
});

app.get("/venues/:venue/symbols", async (request, response, next) => {
  try {
    const venue = request.params.venue;
    if (venue !== "binance" && venue !== "binance-testnet") {
      response.status(404).json({ error: "Venue not found" });
      return;
    }

    response.json({
      venue,
      label: venue === "binance-testnet" ? "Binance Testnet" : "Binance",
      symbols: await getVenueSymbols("binance")
    });
  } catch (error) {
    next(error);
  }
});

app.get("/venues/:venue/balance", async (request, response, next) => {
  try {
    const venue = request.params.venue;
    const mode = venue === "binance-testnet" ? "testnet" as const : "live" as const;
    const balance = await getAccountBalance(mode);

    const allocatedBudgets = await sql<{ total: string }[]>`
      select coalesce(sum(budget_usdt), 0)::text as total
      from bot_runtime_configs
      where venue = ${venue}
        and enabled = true
    `;
    const allocatedUsdt = Number(allocatedBudgets[0]?.total ?? 0);

    response.json({
      venue,
      totalFreeUsdt: balance.totalFreeUsdt,
      allocatedUsdt,
      availableUsdt: Math.max(0, balance.totalFreeUsdt - allocatedUsdt)
    });
  } catch (error) {
    next(error);
  }
});

app.post("/prompts", async (request, response, next) => {
  try {
    const { name, slug, initialBody } = request.body;
    const result = await createPrompt({ name, slug, initialBody });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

app.get("/prompts/versions/:versionId/body", async (request, response, next) => {
  try {
    const version = await getPromptVersionBody(request.params.versionId);
    if (!version) {
      response.status(404).json({ error: "Prompt version not found" });
      return;
    }
    response.json(version);
  } catch (error) {
    next(error);
  }
});

app.post("/prompts/:promptId/versions", async (request, response, next) => {
  try {
    const { body } = request.body;
    if (!body || typeof body !== "string" || !body.trim()) {
      response.status(400).json({ error: "body is required" });
      return;
    }
    const result = await addPromptVersion({ promptId: request.params.promptId, body: body.trim() });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

app.get("/models", async (request, response, next) => {
  try {
    const provider = typeof request.query.provider === "string" ? request.query.provider : undefined;
    let liveXaiModelIds: Set<string> | null = null;
    let liveXaiModels: Array<{ id: string; created: number | null }> = [];
    const providersToSync = provider ? [provider] : [...SUPPORTED_MODEL_PROVIDERS];

    for (const providerName of providersToSync) {
      try {
        await syncProviderModels(providerName);
      } catch (syncError) {
        console.warn(`${providerName} sync failed:`, String(syncError));
      }
    }

    try {
      await bootstrapModelProfiles();
    } catch (bootstrapError) {
      console.warn("Model bootstrap failed:", String(bootstrapError));
    }

    if (!provider || provider === "xai") {
      try {
        liveXaiModels = await listXaiModels();
        liveXaiModelIds = new Set(liveXaiModels.map((model) => model.id));
      } catch (liveCatalogError) {
        console.warn("xAI live catalog check failed, serving cached profiles:", String(liveCatalogError));
      }
    }

    let profiles: Array<Record<string, unknown>>;
    try {
      profiles = await listModelProfiles(provider) as Array<Record<string, unknown>>;
    } catch (dbError) {
      console.warn("DB query for model profiles failed, building response from xAI live catalog:", String(dbError));
      if (liveXaiModels.length > 0 && (!provider || provider === "xai")) {
        profiles = liveXaiModels.map((m) => ({
          id: `live:xai:${m.id}`,
          name: `xAI ${m.id}`,
          provider: "xai",
          model: m.id,
          settings: { temperature: 0.2 }
        }));
        response.json(profiles);
        return;
      }
      const fallback = BOOTSTRAP_XAI_PROFILES.map((p) => ({
        id: `fallback:xai:${p.model}`,
        name: p.name,
        provider: "xai",
        model: p.model,
        settings: { temperature: 0.2 }
      })).concat(BOOTSTRAP_NOUS_PROFILES.map((p) => ({
        id: `fallback:nous:${p.model}`,
        name: p.name,
        provider: "nous",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_OPENAI_PROFILES.map((p) => ({
        id: `fallback:openai:${p.model}`,
        name: p.name,
        provider: "openai",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_ANTHROPIC_PROFILES.map((p) => ({
        id: `fallback:anthropic:${p.model}`,
        name: p.name,
        provider: "anthropic",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_GOOGLE_PROFILES.map((p) => ({
        id: `fallback:google:${p.model}`,
        name: p.name,
        provider: "google",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_MISTRAL_PROFILES.map((p) => ({
        id: `fallback:mistral:${p.model}`,
        name: p.name,
        provider: "mistral",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_HUGGINGFACE_PROFILES.map((p) => ({
        id: `fallback:huggingface:${p.model}`,
        name: p.name,
        provider: "huggingface",
        model: p.model,
        settings: { temperature: 0.2 }
      })));
      response.json(fallback);
      return;
    }

    if (provider === "xai" && liveXaiModelIds && liveXaiModelIds.size > 0) {
      response.json(profiles.filter((profile) => liveXaiModelIds!.has(String(profile.model)) || ALWAYS_KEEP_XAI_MODEL_IDS.has(String(profile.model))));
      return;
    }

    if (!provider && liveXaiModelIds && liveXaiModelIds.size > 0) {
      response.json(
        profiles.filter((profile) => profile.provider !== "xai" || liveXaiModelIds!.has(String(profile.model)) || ALWAYS_KEEP_XAI_MODEL_IDS.has(String(profile.model)))
      );
      return;
    }

    response.json(profiles);
  } catch (error) {
    next(error);
  }
});

app.post("/models", async (request, response, next) => {
  try {
    const { name, provider, model, settings } = request.body;
    const id = await createModelProfile({ name, provider, model, settings });
    response.json({ id });
  } catch (error) {
    next(error);
  }
});

app.post("/internal/catalog/sync", async (request, response, next) => {
  try {
    const force = request.query.force === "true";
    const provider = typeof request.query.provider === "string" ? request.query.provider : "all";
    const providersToSync = provider === "all" ? [...SUPPORTED_MODEL_PROVIDERS] : [provider];
    const syncResults = [];
    let bootstrapResult = { count: 0, inserted: 0, updated: 0 };

    for (const providerName of providersToSync) {
      try {
        syncResults.push({
          provider: providerName,
          label: modelProviderLabel(providerName),
          ...(await syncProviderModels(providerName, force))
        });
      } catch (syncError) {
        console.warn(`${providerName} sync failed:`, String(syncError));
        syncResults.push({
          provider: providerName,
          label: modelProviderLabel(providerName),
          synced: false,
          count: 0,
          inserted: 0,
          updated: 0,
          message: String(syncError)
        });
      }
    }

    try {
      bootstrapResult = await bootstrapModelProfiles();
    } catch (bootstrapError) {
      console.warn("Model bootstrap failed:", String(bootstrapError));
    }

    const models = await listModelProfiles(provider === "all" ? undefined : provider);

    response.json({
      ok: true,
      provider,
      modelCount: models.length,
      syncedAt: new Date().toISOString(),
      sync: syncResults,
      bootstrap: bootstrapResult,
      models: models.map(m => ({ id: m.id, name: m.name, provider: m.provider, model: m.model }))
    });
  } catch (error) {
    next(error);
  }
});

app.get("/trader-prompts", async (_request, response, next) => {
  try {
    response.json(await listTraderPrompts());
  } catch (error) {
    next(error);
  }
});

app.post("/trader-prompts", async (request, response, next) => {
  try {
    const { name, slug, initialBody } = request.body;
    if (!initialBody || typeof initialBody !== "string" || !initialBody.trim()) {
      response.status(400).json({ error: "initialBody is required" });
      return;
    }
    const result = await createTraderPrompt({ name, slug, initialBody: initialBody.trim() });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

app.post("/bots", async (request, response, next) => {
  try {
    const { name, slug, promptVersionId, modelProfileId, traderModelProfileId, promptConfig, traderConfig, traderPromptVersionId, parentBotId, enabled, runtimeConfig } =
      request.body;
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
      runtimeConfig: botCreateRuntimeConfigSchema.parse(runtimeConfig)
    });

    // Track prompt usage
    if (promptVersionId) void touchResearchPromptUsage(promptVersionId).catch(() => {});
    if (traderPromptVersionId) void touchTraderPromptUsage(traderPromptVersionId).catch(() => {});

    response.json({
      id,
      initialRunQueued: true,
      schedulerEnabled: env.SCHEDULER_ENABLED
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

app.patch("/bots/:botId", async (request, response, next) => {
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
      mode,
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
      mode !== undefined ||
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
          mode:
            mode ??
            runtimeConfig?.mode ??
            ((venue ?? runtimeConfig?.venue) === "binance-testnet" ? "testnet" : current.runtimeConfig.mode),
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

// ── v2: Kill All Bots (one-shot panic) ───────────────────────────────

app.post("/bots/kill-all", async (_request, response, next) => {
  try {
    const bots = await getAllEnabledBotSetups();
    if (bots.length === 0) {
      response.json({ killed: 0, results: [] });
      return;
    }

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

// ── v2: LLM Call Logs ────────────────────────────────────────────────

app.get("/runs/:runId/llm-calls", async (request, response, next) => {
  try {
    const calls = await getLLMCallsForRun(request.params.runId);
    response.json({ runId: request.params.runId, calls });
  } catch (error) {
    next(error);
  }
});

// ── v2: MCP Tool List ────────────────────────────────────────────────

app.get("/mcp/tools", async (_request, response) => {
  response.json({ tools: listTools() });
});

// ── Error Handler ────────────────────────────────────────────────────

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  console.error(error);
  response.status(500).json({
    error: error instanceof Error ? error.message : "Unknown server error"
  });
});

const CATALOG_SYNC_INTERVAL_MS = 30 * 60 * 1000;

const startCatalogSyncLoop = () => {
  const runSync = async () => {
    try {
      for (const provider of SUPPORTED_MODEL_PROVIDERS) {
        try {
          await syncProviderModels(provider);
        } catch (providerError) {
          console.warn(`Background ${provider} catalog sync failed:`, String(providerError));
        }
      }
      await bootstrapModelProfiles();
    } catch (error) {
      console.warn("Background catalog sync failed:", String(error));
    }
  };

  void runSync();
  setInterval(() => {
    void runSync();
  }, CATALOG_SYNC_INTERVAL_MS);
};

const SCHEDULER_INTERVAL_MS = 15 * 1000; // 15 seconds to ensure we don't miss the frequency

let schedulerLoopStarted = false;
let schedulerTickRunning = false;
let schedulerLastTickAt: string | null = null;
let schedulerLastFinishedAt: string | null = null;
let schedulerLastError: string | null = null;
let schedulerLastDueBotCount = 0;
let schedulerLastResultCount = 0;

const getSchedulerStatus = () => ({
  enabled: env.SCHEDULER_ENABLED,
  loopStarted: schedulerLoopStarted,
  tickRunning: schedulerTickRunning,
  intervalMs: SCHEDULER_INTERVAL_MS,
  lastTickAt: schedulerLastTickAt,
  lastFinishedAt: schedulerLastFinishedAt,
  lastDueBotCount: schedulerLastDueBotCount,
  lastResultCount: schedulerLastResultCount,
  lastError: schedulerLastError
});

const runSchedulerTick = async (trigger: "startup" | "interval" | "manual") => {
  if (schedulerTickRunning) {
    return {
      checkedAt: new Date().toISOString(),
      trigger,
      skipped: true,
      reason: "scheduler_tick_already_running",
      dueBotCount: schedulerLastDueBotCount,
      results: []
    };
  }

  schedulerTickRunning = true;
  schedulerLastTickAt = new Date().toISOString();

  try {
    const dueBots = await getDueBots();
    const results: Array<Record<string, unknown>> = [];

    for (const bot of dueBots) {
      try {
        const result = await runBot(bot);
        results.push({ botId: bot.id, ...result });
      } catch (error) {
        results.push({
          botId: bot.id,
          status: "failure",
          error: error instanceof Error ? error.message : "Unknown run error"
        });
      }
    }

    schedulerLastError = null;
    schedulerLastDueBotCount = dueBots.length;
    schedulerLastResultCount = results.length;
    schedulerLastFinishedAt = new Date().toISOString();

    return {
      checkedAt: schedulerLastFinishedAt,
      trigger,
      skipped: false,
      dueBotCount: dueBots.length,
      results
    };
  } catch (error) {
    schedulerLastError = error instanceof Error ? error.message : String(error);
    schedulerLastFinishedAt = new Date().toISOString();
    console.warn("Background scheduler tick failed:", schedulerLastError);
    throw error;
  } finally {
    schedulerTickRunning = false;
  }
};

const startSchedulerLoop = () => {
  schedulerLoopStarted = true;
  void runSchedulerTick("startup").catch(() => {});
  setInterval(() => {
    void runSchedulerTick("interval").catch(() => {});
  }, SCHEDULER_INTERVAL_MS);
};

app.listen(env.API_PORT, "0.0.0.0", () => {
  startCatalogSyncLoop();
  if (env.SCHEDULER_ENABLED) {
    startSchedulerLoop();
  } else {
    console.log("[scheduler] disabled; set SCHEDULER_ENABLED=true to run due bots automatically");
  }
  if (env.GUARDIAN_ENABLED) {
    startGuardian();
  } else {
    console.log("[guardian] disabled; set GUARDIAN_ENABLED=true to run position safety checks");
  }
  console.log(`API listening on http://0.0.0.0:${env.API_PORT}`);
});
