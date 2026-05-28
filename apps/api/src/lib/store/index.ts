// Re-export all store modules for backward compatibility.
// New code should import from specific modules directly.

export type { BotSetup, BotExecutionLedgerEntry } from "./bots.js";
export {
  getDueBots,
  ensureBotSchedulerSchema,
  getAllEnabledBotSetups,
  getBotSetupById,
  claimRun,
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
  markRuntimeRunFinished,
  recentTradeAlerts,
  getRunDetail,
  getBotRuns
} from "./runs.js";

export { storeExecutionRecords } from "./executions.js";
export type { StoredExecution } from "./executions.js";

export {
  openPosition,
  listActivePositions,
  listActivePositionsForBotSymbol,
  closePosition,
  updateSafetyStop,
  applySellToOpenPositions
} from "./positions.js";
export type { BotPosition, PositionCloseReason } from "./positions.js";
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
  touchResearchPromptUsage,
  getLatestResearchPromptVersion,
  getLatestModelProfile
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
export { getAppSetting, setAppSetting, getAppSettings, setAppSettings } from "./settings.js";

export {
  createAgentStep,
  finishAgentStep,
  recordAgentStep,
  listAgentSteps,
  getAgentControlSummary,
  createApprovalRequest,
  listApprovalRequests,
  getApprovalRequest,
  updateApprovalStatus
} from "./agent-steps.js";
export type { ApprovalRequest } from "./agent-steps.js";

export {
  createResearchExperiment,
  updateResearchExperiment,
  getResearchExperiment,
  listResearchExperiments,
  listResearchDataSources,
  createResearchDataSource,
  updateResearchDataSource,
  createResearchCandidate,
  getResearchCandidate,
  getPendingLivePromotionApprovalForCandidate,
  setCandidatePromotedBot,
  setCandidatePaperBot,
  listResearchCandidates
} from "./research.js";

export {
  listDatasets,
  createDataset,
  createDatasetVersion,
  listDatasetVersions,
  getDatasetVersion,
  createResearchSession,
  listResearchSessions,
  getResearchSession,
  updateResearchSession,
  createResearchEngineRun,
  listResearchEngineRuns,
  updateResearchEngineRun,
  createExperimentSpec,
  listExperimentSpecs,
  getExperimentSpec,
  updateExperimentSpec,
  createEvaluationResult,
  createEvaluationJob,
  updateEvaluationJob,
  listEvaluationJobs,
  getEvaluationJob,
  createResearchMemory,
  listResearchMemories,
  updateResearchMemory
} from "./research-kernel.js";

export {
  listRawObservations,
  listStandardizedSignals,
  createRawObservation,
  createStandardizedSignal,
  updateStandardizedSignalStatus
} from "./signals.js";

export type { JsonValue } from "./helpers.js";
export { parseJson, toIsoString, buildRuntimeConfig } from "./helpers.js";
