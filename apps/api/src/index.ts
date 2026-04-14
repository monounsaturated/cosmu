import cors from "cors";
import express from "express";
import { env } from "./env.js";
import {
  addPromptVersion,
  createBot,
  createModelProfile,
  createPrompt,
  getBotSetupById,
  getDashboard,
  getDueBots,
  getPromptVersionBody,
  listModelProfiles,
  listPrompts,
  toggleBotEnabled,
  updateBotConfig
} from "./lib/store.js";
import { getVenueSymbols, syncProviderModels } from "./services/catalog.js";
import { notifySlack } from "./services/notifier.js";
import { runBot } from "./services/run-bot.js";

const app = express();

app.use(
  cors(
    env.WEB_BASE_URL
      ? {
          origin: env.WEB_BASE_URL
        }
      : undefined
  )
);
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

app.get("/health", async (_request, response) => {
  response.json({
    ok: true,
    mode: "runtime"
  });
});

app.get("/internal/qa/status", async (_request, response) => {
  response.json({
    ok: true,
    runtime: {
      port: env.API_PORT,
      corsOriginMode: env.WEB_BASE_URL ? "strict" : "open"
    },
    envReadiness: {
      database: Boolean(env.DATABASE_URL),
      apiSecretConfigured: env.API_SECRET_KEY.length >= 32,
      xaiConfigured: Boolean(env.XAI_API_KEY),
      binanceConfigured: Boolean(env.BINANCE_API_KEY && env.BINANCE_API_SECRET),
      slackConfigured: Boolean(env.SLACK_WEBHOOK_URL),
      webBaseUrlConfigured: Boolean(env.WEB_BASE_URL)
    }
  });
});

app.get("/dashboard", async (_request, response, next) => {
  try {
    response.json(await getDashboard());
  } catch (error) {
    next(error);
  }
});

app.patch("/bots/:botId/toggle", async (request, response, next) => {
  try {
    const result = await toggleBotEnabled(request.params.botId);
    if (!result) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    await notifySlack(`Bot ${result.name} ${result.enabled ? "enabled" : "disabled"}`);
    response.json({ id: request.params.botId, name: result.name, enabled: result.enabled });
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
      response.status(409).json({ error: "Bot is disabled. Enable it before triggering a run." });
      return;
    }

    const result = await runBot(bot);
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

app.post("/internal/scheduler/tick", async (_request, response, next) => {
  try {
    const dueBots = await getDueBots();
    const results = [];

    for (const bot of dueBots) {
      try {
        results.push(await runBot(bot));
      } catch (error) {
        results.push({
          botId: bot.id,
          status: "failure",
          error: error instanceof Error ? error.message : "Unknown run error"
        });
      }
    }

    response.json({
      checkedAt: new Date().toISOString(),
      dueBotCount: dueBots.length,
      results
    });
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
    if (request.params.venue !== "binance") {
      response.status(404).json({ error: "Venue not found" });
      return;
    }

    response.json({
      venue: "binance",
      label: "Binance France",
      symbols: await getVenueSymbols("binance")
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

    if (!provider || provider === "xai") {
      try {
        await syncProviderModels("xai");
      } catch (syncError) {
        console.warn("Model sync failed, serving cached profiles:", syncError);
      }
    }

    response.json(await listModelProfiles(provider));
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

app.post("/bots", async (request, response, next) => {
  try {
    const { name, slug, promptVersionId, modelProfileId, promptConfig, traderConfig, parentBotId, runtimeConfig } =
      request.body;
    const id = await createBot({
      name,
      slug,
      promptVersionId,
      modelProfileId,
      promptConfig,
      traderConfig,
      parentBotId,
      runtimeConfig
    });
    response.json({ id });
  } catch (error) {
    next(error);
  }
});

app.patch("/bots/:botId", async (request, response, next) => {
  try {
    const { name, enabled, promptVersionId, modelProfileId, frequencyMinutes, mode, contextSymbols, execution } =
      request.body;

    if (
      promptVersionId !== undefined ||
      modelProfileId !== undefined ||
      frequencyMinutes !== undefined ||
      mode !== undefined ||
      contextSymbols !== undefined ||
      execution !== undefined
    ) {
      response.status(409).json({
        error: "Bot strategy is immutable after creation. Create a new bot to test another prompt, model, or settings."
      });
      return;
    }

    await updateBotConfig(request.params.botId, {
      name,
      enabled
    });
    response.json({ ok: true });
  } catch (error) {
    next(error);
  }
});

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  console.error(error);
  response.status(500).json({
    error: error instanceof Error ? error.message : "Unknown server error"
  });
});

app.listen(env.API_PORT, "0.0.0.0", () => {
  console.log(`API listening on http://0.0.0.0:${env.API_PORT}`);
});
