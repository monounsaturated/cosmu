// module: Boot/manage Railway background loops (scheduler, guardian, market-data cache).
import { ensureBotSchedulerSchema, ensureIndexSchema } from "../lib/store.js";
import { getGuardianStatus, startGuardian } from "./guardian.js";
import {
  BOT_SCHEDULER_INTERVAL_MS,
  getSchedulerStatus,
  runSchedulerTick,
  type SchedulerTrigger
} from "./bot-scheduler.js";
import {
  INDEX_SCHEDULER_INTERVAL_MS,
  getIndexSchedulerStatus,
  runIndexSchedulerTick
} from "./index-runner.js";
import {
  CATALOG_REFRESH_INTERVAL_MS,
  syncAllProviderModels,
  syncVenueSymbols
} from "./catalog.js";
import { PRICING_REFRESH_INTERVAL_MS, refreshLlmPricingCatalog } from "./llm-spend.js";
import { MARKET_DATA_REFRESH_INTERVAL_MS, refreshMarketDataSnapshot } from "./market-data-cache.js";

type BackgroundJobTrigger = "startup" | "interval" | "manual";
export type BackgroundJobId =
  | "bot-scheduler"
  | "index-scheduler"
  | "market-data-refresh"
  | "llm-pricing-sync"
  | "model-catalog-sync"
  | "venue-symbol-sync";

type BackgroundJobDefinition = {
  id: BackgroundJobId;
  label: string;
  description: string;
  intervalMs: number;
  enabled: () => boolean;
  run: (trigger: BackgroundJobTrigger) => Promise<unknown>;
};

type BackgroundJobStatus = {
  id: BackgroundJobId;
  label: string;
  description: string;
  enabled: boolean;
  intervalMs: number;
  running: boolean;
  runCount: number;
  lastStartedAt: string | null;
  lastFinishedAt: string | null;
  lastError: string | null;
  nextRunAt: string | null;
  lastTrigger: BackgroundJobTrigger | null;
  lastResult: unknown;
};

const BACKGROUND_JOB_LOOP_INTERVAL_MS = BOT_SCHEDULER_INTERVAL_MS;
const BACKGROUND_BOOTSTRAP_RETRY_MS = 15 * 1000;

let backgroundServicesStarted = false;
let backgroundServicesStarting = false;
let backgroundJobLoopStarted = false;
let backgroundJobLoop: NodeJS.Timeout | null = null;
let backgroundBootstrapRetry: NodeJS.Timeout | null = null;
let backgroundBootstrapLastError: string | null = null;
let backgroundBootstrapNextRetryAt: string | null = null;

const schedulerTriggerFromBackground = (trigger: BackgroundJobTrigger): SchedulerTrigger =>
  trigger === "manual" ? "manual" : trigger;

const JOB_DEFINITIONS: BackgroundJobDefinition[] = [
  {
    id: "bot-scheduler",
    label: "Bot scheduler",
    description: "Claims due enabled bots and runs one non-overlapping cycle per bot.",
    intervalMs: BOT_SCHEDULER_INTERVAL_MS,
    enabled: () => true,
    run: (trigger) => runSchedulerTick(schedulerTriggerFromBackground(trigger))
  },
  {
    id: "index-scheduler",
    label: "Index scheduler",
    description: "Claims due active index configs and writes one snapshot per index per cadence.",
    intervalMs: INDEX_SCHEDULER_INTERVAL_MS,
    enabled: () => true,
    run: (trigger) => runIndexSchedulerTick(trigger === "manual" ? "manual" : trigger === "startup" ? "startup" : "interval")
  },
  {
    id: "market-data-refresh",
    label: "Market data cache",
    description: "Refreshes cached Binance prices and account balances so dashboard requests stay fast.",
    intervalMs: MARKET_DATA_REFRESH_INTERVAL_MS,
    enabled: () => true,
    run: (trigger) => refreshMarketDataSnapshot(trigger === "startup" ? "startup" : trigger === "manual" ? "manual" : "interval")
  },
  {
    id: "llm-pricing-sync",
    label: "LLM pricing sync",
    description: "Refreshes provider pricing source data used by spend estimates.",
    intervalMs: PRICING_REFRESH_INTERVAL_MS,
    enabled: () => true,
    run: (trigger) => refreshLlmPricingCatalog(trigger !== "startup")
  },
  {
    id: "model-catalog-sync",
    label: "Model catalog sync",
    description: "Fetches available provider models so new agents can use current model catalogs.",
    intervalMs: CATALOG_REFRESH_INTERVAL_MS,
    enabled: () => true,
    run: (trigger) => syncAllProviderModels(trigger !== "startup")
  },
  {
    id: "venue-symbol-sync",
    label: "Venue symbol sync",
    description: "Refreshes tradable venue symbols used by agent prompts and validation.",
    intervalMs: CATALOG_REFRESH_INTERVAL_MS,
    enabled: () => true,
    run: async (trigger) => ({
      live: await syncVenueSymbols("binance", trigger !== "startup"),
      testnet: await syncVenueSymbols("binance-testnet", trigger !== "startup")
    })
  }
];

const jobStatuses = new Map<BackgroundJobId, BackgroundJobStatus>(
  JOB_DEFINITIONS.map((job) => [
    job.id,
    {
      id: job.id,
      label: job.label,
      description: job.description,
      enabled: job.enabled(),
      intervalMs: job.intervalMs,
      running: false,
      runCount: 0,
      lastStartedAt: null,
      lastFinishedAt: null,
      lastError: null,
      nextRunAt: null,
      lastTrigger: null,
      lastResult: null
    }
  ])
);

const getJobDefinition = (id: BackgroundJobId) => JOB_DEFINITIONS.find((job) => job.id === id) ?? null;

const scheduleNextRun = (status: BackgroundJobStatus, intervalMs: number) => {
  status.nextRunAt = new Date(Date.now() + intervalMs).toISOString();
};

export const runBackgroundJob = async (id: BackgroundJobId, trigger: BackgroundJobTrigger = "manual") => {
  const job = getJobDefinition(id);
  if (!job) {
    throw new Error(`Unknown background job: ${id}`);
  }

  const status = jobStatuses.get(id)!;
  status.enabled = job.enabled();

  if (!status.enabled && trigger !== "manual") {
    return {
      id,
      skipped: true,
      reason: "job_disabled",
      checkedAt: new Date().toISOString()
    };
  }

  if (status.running) {
    return {
      id,
      skipped: true,
      reason: "job_already_running",
      checkedAt: new Date().toISOString()
    };
  }

  status.running = true;
  status.lastStartedAt = new Date().toISOString();
  status.lastTrigger = trigger;

  try {
    const result = await job.run(trigger);
    status.runCount += 1;
    status.lastResult = result;
    status.lastError = null;
    status.lastFinishedAt = new Date().toISOString();
    scheduleNextRun(status, job.intervalMs);
    return {
      id,
      skipped: false,
      checkedAt: status.lastFinishedAt,
      result
    };
  } catch (error) {
    status.lastError = error instanceof Error ? error.message : String(error);
    status.lastFinishedAt = new Date().toISOString();
    scheduleNextRun(status, job.intervalMs);
    console.warn(`[background-jobs] ${id} failed:`, status.lastError);
    throw error;
  } finally {
    status.running = false;
  }
};

const runBackgroundJobSettled = async (id: BackgroundJobId, trigger: BackgroundJobTrigger) => {
  try {
    return await runBackgroundJob(id, trigger);
  } catch (error) {
    return {
      id,
      skipped: false,
      failed: true,
      checkedAt: new Date().toISOString(),
      error: error instanceof Error ? error.message : String(error)
    };
  }
};

export const runDueBackgroundJobs = async (trigger: BackgroundJobTrigger = "interval") => {
  const now = Date.now();
  const results = [];

  for (const job of JOB_DEFINITIONS) {
    const status = jobStatuses.get(job.id)!;
    status.enabled = job.enabled();
    if (!status.enabled) continue;
    if (status.nextRunAt && new Date(status.nextRunAt).getTime() > now) continue;
    results.push(await runBackgroundJobSettled(job.id, trigger));
  }

  return {
    checkedAt: new Date().toISOString(),
    trigger,
    results
  };
};

export const runHourlyBackgroundJobs = async (trigger: BackgroundJobTrigger = "manual") => ({
  checkedAt: new Date().toISOString(),
  trigger,
  results: [
    await runBackgroundJobSettled("llm-pricing-sync", trigger),
    await runBackgroundJobSettled("model-catalog-sync", trigger),
    await runBackgroundJobSettled("venue-symbol-sync", trigger)
  ]
});

const startBackgroundJobLoop = () => {
  if (backgroundJobLoopStarted) return;

  backgroundJobLoopStarted = true;
  backgroundJobLoop = setInterval(() => {
    void runDueBackgroundJobs("interval").catch((error) => {
      console.warn("[background-jobs] interval loop failed:", error instanceof Error ? error.message : String(error));
    });
  }, BACKGROUND_JOB_LOOP_INTERVAL_MS);

  void runDueBackgroundJobs("startup").catch((error) => {
    console.warn("[background-jobs] startup run failed:", error instanceof Error ? error.message : String(error));
  });
};

const scheduleBackgroundBootstrapRetry = () => {
  if (backgroundBootstrapRetry) return;

  const retryAt = new Date(Date.now() + BACKGROUND_BOOTSTRAP_RETRY_MS);
  backgroundBootstrapNextRetryAt = retryAt.toISOString();
  backgroundBootstrapRetry = setTimeout(() => {
    backgroundBootstrapRetry = null;
    backgroundBootstrapNextRetryAt = null;
    void startRuntimeAutomation();
  }, BACKGROUND_BOOTSTRAP_RETRY_MS);
};

export const startRuntimeAutomation = async () => {
  if (backgroundServicesStarted || backgroundServicesStarting) return;

  backgroundServicesStarting = true;
  try {
    await ensureBotSchedulerSchema();
    await ensureIndexSchema();
    startBackgroundJobLoop();
    startGuardian();

    backgroundServicesStarted = true;
    backgroundBootstrapLastError = null;
  } catch (error) {
    backgroundBootstrapLastError = error instanceof Error ? error.message : String(error);
    console.error("[startup] runtime automation failed; retrying:", backgroundBootstrapLastError);
    scheduleBackgroundBootstrapRetry();
  } finally {
    backgroundServicesStarting = false;
  }
};

export const getRuntimeAutomationStatus = () => ({
  servicesStarted: backgroundServicesStarted,
  servicesStarting: backgroundServicesStarting,
  bootstrapLastError: backgroundBootstrapLastError,
  bootstrapNextRetryAt: backgroundBootstrapNextRetryAt,
  loopStarted: backgroundJobLoopStarted,
  intervalActive: Boolean(backgroundJobLoop),
  intervalMs: BACKGROUND_JOB_LOOP_INTERVAL_MS,
  scheduler: getSchedulerStatus(),
  indexScheduler: getIndexSchedulerStatus(),
  guardian: getGuardianStatus(),
  jobs: Array.from(jobStatuses.values()).map((status) => ({
    ...status,
    enabled: getJobDefinition(status.id)?.enabled() ?? status.enabled
  }))
});
