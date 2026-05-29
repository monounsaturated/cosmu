// module: App settings — LLM providers, agent defaults, feature toggles, prompt runtime templates.
import { z } from "zod";
import { venueSchema } from "./venue.js";
import { symbolScopeSchema } from "./trading.js";

export const llmProviderSchema = z.enum(["xai", "nous", "openai", "anthropic", "huggingface", "google", "mistral"]);
export type LlmProvider = z.infer<typeof llmProviderSchema>;

const DEFAULT_PROMPT_DEFAULT = { mode: "new", versionId: null } as const;
const DEFAULT_SAVED_PROMPT_DEFAULT = { mode: "saved", versionId: null } as const;
const DEFAULT_PHASE_DEFAULT = { provider: "xai", modelProfileId: null, prompt: DEFAULT_SAVED_PROMPT_DEFAULT } as const;
const DEFAULT_TRADER_PHASE_DEFAULT = { provider: "xai", modelProfileId: null, prompt: DEFAULT_SAVED_PROMPT_DEFAULT } as const;
const DEFAULT_RUNTIME_EXECUTION = {
  enabled: false,
  maxDrawdownEnabled: false,
  allowMarketOrders: true,
  allowLimitOrders: true,
  maxOrdersPerRun: 3,
  maxNotionalPerOrderUsd: 250,
  minCashReserveUsd: 25,
  maxDrawdownPct: 10
} as const;
const DEFAULT_RUNTIME_DEFAULTS = {
  venue: "binance-testnet",
  frequencyMinutes: 30,
  budgetUsdt: 1000,
  symbolScope: "all",
  execution: DEFAULT_RUNTIME_EXECUTION
} as const;
const DEFAULT_FEATURE_TOGGLES = {
  promptLab: false,
  sentiment: false,
  signals: false,
  researchLab: false,
  promptLibrary: false
} as const;

export const defaultFeatureToggles = DEFAULT_FEATURE_TOGGLES;

export const DEFAULT_RESEARCH_GROUNDING_RULES = [
  "---",
  "GROUNDING RULES (critical - your output feeds live trading decisions):",
  "- Today's date is {date}. Use the available tools and injected data before making current-market claims.",
  "- For recent or time-sensitive claims about prices, liquidity, volume, news, social posts/tweets, filings, macro events, or market structure: search or query an available tool first.",
  "- Justify every material claim with the retrieved source, timestamp, or data point. If you cannot verify something, say that it is unverified and do not use it as a reason to trade.",
  "- Do not invent headlines, tweet/post authors, dates, prices, or catalysts. A short, honest report with uncertainty is better than a confident fabrication.",
  "- Distinguish facts retrieved this run from your interpretation. Keep speculation clearly labeled."
].join("\n");

export const DEFAULT_INJECTED_DATA_TEMPLATES = {
  researchGrounding: {
    label: "Grounding Rules",
    preview: DEFAULT_RESEARCH_GROUNDING_RULES
  },
  traderResearchOutput: {
    label: "Research Output",
    preview: "=== UPSTREAM RESEARCH (phase 1 analysis) ===\n[The full output from the research agent will appear here.]"
  },
  traderSession: {
    label: "Session",
    preview: "=== SESSION ===\nBot: My Strategy (#32) | Model: xAI grok-4.3\nMode: testnet | Venue: Binance Spot | Frequency: every 30min\nBudget: $1,000.00 - you must stay within this allocation"
  },
  traderExecutionRules: {
    label: "Execution Rules",
    preview: "=== EXECUTION RULES ===\nOrder caps: OFF\nMax drawdown kill: OFF\nAllowed types: MARKET, LIMIT"
  },
  traderWallet: {
    label: "Wallet",
    preview: "=== WALLET ===\nTotal: $1,072.50\nUSDT: 500.00 free ($500.00)\nUSDC: 250.20 free ($250.20)\nBTC: 0.0012 free ($82.14)\nETH: 0.15 free ($361.50)"
  },
  traderTradingScope: {
    label: "Trading Scope",
    preview: "=== TRADING SCOPE ===\nYou may trade any authorized stable-quoted spot pair available on Binance."
  },
  traderNonNegotiable: {
    label: "Non-Negotiable Constraints",
    preview: [
      "---",
      "HARD RULES:",
      "- Buy only symbols verified this turn with binance_symbol_lookup; use its canonical symbol and currentPrice.",
      "- BUY: stopLossPrice < currentPrice and takeProfitPrice > currentPrice. SELL: both null.",
      "- If no valid trade survives, return hold with orders: [].",
      "- Final answer: one TradingDecision JSON object, no markdown or prose."
    ].join("\n")
  },
  includeWalletOverview: {
    label: "Portfolio Overview",
    preview: "=== PORTFOLIO OVERVIEW ===\nStarted: $1,000.00 | Now: $1,072.50 | Net PnL: $72.50\nRuns: 24 | Trades: 18 | Fees: $3.40"
  },
  includePerformanceStats: {
    label: "Performance Stats",
    preview: "=== PERFORMANCE STATS ===\n{\n  \"runCount\": 24,\n  \"tradeCount\": 18,\n  \"totalFeesUsd\": 3.40,\n  \"firstPortfolioUsd\": 1000,\n  \"currentPortfolioUsd\": 1072.50,\n  \"netPnlUsd\": 72.50\n}"
  },
  includeBotRanking: {
    label: "Bot Rankings",
    preview: "=== BOT RANKINGS ===\n1. Alpha Momentum: $142.30 net PnL\n2. Swing Macro: $72.50 net PnL\n3. This Bot: $45.20 net PnL"
  },
  includePastTrades: {
    label: "Past Trades",
    preview: "=== RECENT TRADES (last 10) ===\nBUY BTCUSDT qty=0.0012 @ 68450 -> success\nSELL ETHUSDT qty=0.15 @ 2410 -> success\nBUY SOLUSDT qty=2.5 @ 142.80 -> success"
  }
} as const;

export const promptDefaultSchema = z.object({
  mode: z.enum(["new", "saved"]).default("new"),
  versionId: z.string().uuid().nullable().default(null)
}).default(DEFAULT_PROMPT_DEFAULT);

export const phaseDefaultSchema = z.object({
  provider: llmProviderSchema.default("xai"),
  modelProfileId: z.string().uuid().nullable().default(null),
  prompt: promptDefaultSchema
}).default(DEFAULT_PHASE_DEFAULT);

export const agentRuntimeDefaultsSchema = z.object({
  venue: venueSchema.default("binance-testnet"),
  frequencyMinutes: z.number().int().positive().default(30),
  budgetUsdt: z.number().positive().default(1000),
  symbolScope: symbolScopeSchema.default("all"),
  execution: z.object({
    enabled: z.boolean().default(false),
    maxDrawdownEnabled: z.boolean().default(false),
    allowMarketOrders: z.boolean().default(true),
    allowLimitOrders: z.boolean().default(true),
    maxOrdersPerRun: z.number().int().positive().max(20).default(3),
    maxNotionalPerOrderUsd: z.number().positive().default(250),
    minCashReserveUsd: z.number().nonnegative().default(25),
    maxDrawdownPct: z.number().positive().max(100).default(10)
  }).default(DEFAULT_RUNTIME_EXECUTION)
}).default(DEFAULT_RUNTIME_DEFAULTS);

export const featureTogglesSchema = z.object({
  promptLab: z.boolean().default(false),
  sentiment: z.boolean().default(false),
  signals: z.boolean().default(false),
  researchLab: z.boolean().default(false),
  promptLibrary: z.boolean().default(false)
}).default(DEFAULT_FEATURE_TOGGLES);

const injectedDataTemplateSchema = z.object({
  label: z.string().min(1),
  preview: z.string()
});

export const promptRuntimeSettingsSchema = z.object({
  researchGroundingRules: z.string().min(1).default(DEFAULT_RESEARCH_GROUNDING_RULES),
  injectedDataTemplates: z.object({
    researchGrounding: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.researchGrounding),
    traderResearchOutput: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderResearchOutput),
    traderSession: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderSession),
    traderExecutionRules: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderExecutionRules),
    traderWallet: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderWallet),
    traderTradingScope: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderTradingScope),
    traderNonNegotiable: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.traderNonNegotiable),
    includeWalletOverview: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.includeWalletOverview),
    includePerformanceStats: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.includePerformanceStats),
    includeBotRanking: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.includeBotRanking),
    includePastTrades: injectedDataTemplateSchema.default(DEFAULT_INJECTED_DATA_TEMPLATES.includePastTrades)
  }).default(DEFAULT_INJECTED_DATA_TEMPLATES)
}).default({
  researchGroundingRules: DEFAULT_RESEARCH_GROUNDING_RULES,
  injectedDataTemplates: DEFAULT_INJECTED_DATA_TEMPLATES
});

export const appSettingsSchema = z.object({
  agentDefaults: z.object({
    research: phaseDefaultSchema.default(DEFAULT_PHASE_DEFAULT),
    trader: phaseDefaultSchema.default(DEFAULT_TRADER_PHASE_DEFAULT),
    runtime: agentRuntimeDefaultsSchema.default(DEFAULT_RUNTIME_DEFAULTS)
  }).default({
    research: DEFAULT_PHASE_DEFAULT,
    trader: DEFAULT_TRADER_PHASE_DEFAULT,
    runtime: DEFAULT_RUNTIME_DEFAULTS
  }),
  featureToggles: featureTogglesSchema.default(DEFAULT_FEATURE_TOGGLES),
  promptRuntime: promptRuntimeSettingsSchema
});

export type AppSettings = z.infer<typeof appSettingsSchema>;
export const defaultAppSettings: AppSettings = appSettingsSchema.parse({});
