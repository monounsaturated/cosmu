// Re-export all store modules for backward compatibility.
// New code should import from specific modules directly.

export type { BotSetup, BotExecutionLedgerEntry } from "./bots.js";
export {
  getDueBots,
  getBotSetupById,
  markRunStarted,
  getBotEnabledState,
  killBot,
  createBot,
  updateBotConfig,
  listBotExecutionLedger,
  assetClass
} from "./bots.js";

export {
  createRun,
  storeDecision,
  storeResearchOutput,
  storeTraderOutput,
  updateRunPrompts,
  finishRun,
  recentTradeAlerts,
  getRunDetail,
  getBotRuns
} from "./runs.js";

export { storeExecutionRecords } from "./executions.js";
export { storePortfolioSnapshot } from "./snapshots.js";

export {
  listPrompts,
  listModelProfiles,
  getPromptVersionBody,
  addPromptVersion,
  createPrompt,
  createModelProfile,
  getActiveFormatterPrompt,
  createFormatterPromptVersion,
  listFormatterPromptVersions,
  getAllActiveFormatterPrompts,
  touchResearchPromptUsage
} from "./prompts.js";

export { getBotPrePromptContext } from "./dashboard.js";

export {
  listTraderPrompts,
  createTraderPrompt,
  addTraderPromptVersion,
  getTraderPromptVersionBody,
  getNextTraderPromptNumber,
  touchTraderPromptUsage
} from "./trader-prompts.js";

export { storeLLMCall, getLLMCallsForRun } from "./llm-calls.js";
export { getAppSetting, setAppSetting, isGlobalKillSwitchOn, setGlobalKillSwitch } from "./settings.js";

export type { JsonValue } from "./helpers.js";
export { parseJson, toIsoString, buildRuntimeConfig } from "./helpers.js";
