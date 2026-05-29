// module: System + ops routes — health, diagnostics, dashboard, scheduler/background-jobs, spend, mcp tools.
import { Router, type Router as ExpressRouter } from "express";
import { env } from "../env.js";
import { sql } from "../db.js";
import { listNousModels } from "../providers/nous.js";
import { corsDiagnostics } from "../cors-options.js";
import { getDashboard } from "../services/dashboard.js";
import { getLlmSpendOverview } from "../services/llm-spend.js";
import { listTools } from "../mcp/index.js";
import { runSchedulerTick, triggerSchedulerWatchdog } from "../services/bot-scheduler.js";
import {
  getRuntimeAutomationStatus,
  runBackgroundJob,
  runHourlyBackgroundJobs,
  type BackgroundJobId
} from "../services/background-jobs.js";

export const systemRouter: ExpressRouter = Router();

systemRouter.get("/health", async (_request, response) => {
  response.json({
    ok: true,
    mode: "runtime"
  });
});

systemRouter.get("/internal/diagnostics", async (_request, response) => {
  triggerSchedulerWatchdog("diagnostics");

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
  const automation = getRuntimeAutomationStatus();
  result.automation = automation;
  result.scheduler = {
    ...automation.scheduler,
    loopStarted: automation.loopStarted
  };

  response.json(result);
});

systemRouter.get("/internal/qa/status", async (_request, response) => {
  triggerSchedulerWatchdog("diagnostics");
  const automation = getRuntimeAutomationStatus();

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
      binanceTestnetConfigured: Boolean(env.BINANCE_TESTNET_API_KEY && env.BINANCE_TESTNET_API_SECRET),
      slackConfigured: Boolean(env.SLACK_WEBHOOK_URL),
      webBaseUrlConfigured: Boolean(env.WEB_BASE_URL)
    },
    automation,
    scheduler: {
      ...automation.scheduler,
      loopStarted: automation.loopStarted
    }
  });
});

systemRouter.get("/next-numbers", async (_request, response, next) => {
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

systemRouter.get("/dashboard", async (_request, response, next) => {
  try {
    triggerSchedulerWatchdog("dashboard");
    response.json(await getDashboard());
  } catch (error) {
    next(error);
  }
});

systemRouter.post("/internal/scheduler/tick", async (_request, response, next) => {
  try {
    response.json(await runSchedulerTick("manual"));
  } catch (error) {
    next(error);
  }
});

systemRouter.get("/internal/background-jobs", async (_request, response) => {
  response.json(getRuntimeAutomationStatus());
});

systemRouter.post("/internal/background-jobs/hourly", async (_request, response, next) => {
  try {
    response.json(await runHourlyBackgroundJobs("manual"));
  } catch (error) {
    next(error);
  }
});

systemRouter.post("/internal/background-jobs/:jobId/run", async (request, response, next) => {
  try {
    response.json(await runBackgroundJob(request.params.jobId as BackgroundJobId, "manual"));
  } catch (error) {
    next(error);
  }
});

systemRouter.get("/spend/llm", async (_request, response, next) => {
  const startedAt = Date.now();
  try {
    const overview = await getLlmSpendOverview();
    console.log(`[spend] llm overview served in ${Date.now() - startedAt}ms`);
    response.json(overview);
  } catch (error) {
    next(error);
  }
});

systemRouter.get("/mcp/tools", async (_request, response) => {
  response.json({ tools: listTools() });
});
