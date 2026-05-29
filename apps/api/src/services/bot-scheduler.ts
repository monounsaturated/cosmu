// module: Find due bots and trigger their runs.
import { getDueBots } from "../lib/store.js";
import { runBot } from "./run-bot.js";

export type SchedulerTrigger = "startup" | "interval" | "manual" | "watchdog";

export const BOT_SCHEDULER_INTERVAL_MS = 15 * 1000;

const SCHEDULER_WATCHDOG_MIN_INTERVAL_MS = 10 * 1000;

let schedulerTickRunning = false;
let schedulerLastTickAt: string | null = null;
let schedulerLastFinishedAt: string | null = null;
let schedulerLastError: string | null = null;
let schedulerLastDueBotCount = 0;
let schedulerLastResultCount = 0;
let schedulerWatchdogLastTriggeredAt: string | null = null;
let schedulerWatchdogLastTriggeredMs = 0;

export const getSchedulerStatus = () => ({
  enabled: true,
  intervalMs: BOT_SCHEDULER_INTERVAL_MS,
  tickRunning: schedulerTickRunning,
  watchdogLastTriggeredAt: schedulerWatchdogLastTriggeredAt,
  lastTickAt: schedulerLastTickAt,
  lastFinishedAt: schedulerLastFinishedAt,
  lastDueBotCount: schedulerLastDueBotCount,
  lastResultCount: schedulerLastResultCount,
  lastError: schedulerLastError
});

export const runSchedulerTick = async (trigger: SchedulerTrigger) => {
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

    if (dueBots.length > 0) {
      console.log(`[bot-scheduler] ${trigger} tick found ${dueBots.length} due bot(s)`);
    }

    for (const bot of dueBots) {
      try {
        const result = await runBot(bot);
        results.push({ botId: bot.id, botNumber: bot.botNumber, name: bot.name, ...result });
      } catch (error) {
        results.push({
          botId: bot.id,
          botNumber: bot.botNumber,
          name: bot.name,
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
    console.warn("[bot-scheduler] tick failed:", schedulerLastError);
    throw error;
  } finally {
    schedulerTickRunning = false;
  }
};

export const triggerSchedulerWatchdog = (reason: "dashboard" | "diagnostics" = "dashboard") => {
  if (schedulerTickRunning) return;

  const now = Date.now();
  if (now - schedulerWatchdogLastTriggeredMs < SCHEDULER_WATCHDOG_MIN_INTERVAL_MS) return;

  schedulerWatchdogLastTriggeredMs = now;
  schedulerWatchdogLastTriggeredAt = new Date(now).toISOString();

  void runSchedulerTick("watchdog").catch((error) => {
    console.warn(`[bot-scheduler] ${reason} watchdog tick failed:`, error instanceof Error ? error.message : String(error));
  });
};
