// module: Bot form modal constants, types, prompt defaults, and pure helpers. No React — imported by bot-form-modal.tsx.

export const ALL_SYMBOLS_TOKEN = "__ALL__";

export const DEFAULT_RESEARCH_PROMPT = `You are an autonomous crypto spot trading engine on Binance.

Your goal is to grow the portfolio by finding high-conviction trading opportunities.

Strategy:
- Analyze your current positions, wallet balance, and market conditions
- Look for momentum plays, breakouts, and strong trends in established coins
- Focus on top cryptocurrencies (BTC, ETH, SOL, BNB, XRP) and promising mid-caps
- Enter positions when you see clear setups with favorable risk/reward
- Set stop-loss 3-5% below entry, take-profit 8-15% above entry
- If no clear opportunity exists right now, hold and wait

Position management:
- Keep at least 30% of budget in stablecoins (USDT or USDC) as dry powder
- Maximum 3 open positions at any time
- Cut losers quickly, let winners run

Rules:
- Do not invent balances, prices, or symbols
- Only propose orders for symbols that can plausibly trade against a stablecoin (USDT or USDC)
- Keep the order list lean — quality over quantity
- Every order must include a concise rationale`;

export const DEFAULT_TRADER_PROMPT = `You are phase 2 for one Binance spot bot. Convert research into one valid TradingDecision JSON object.

Use binance_symbol_lookup for candidate tickers. Use its canonical symbol and currentPrice. Ignore stale prices from research.

Respect wallet, authorized pairs, order caps, cash reserve, and allowed order types.

BUY: stopLossPrice below currentPrice and takeProfitPrice above it.
SELL: stopLossPrice and takeProfitPrice null.

If no trade is valid, return hold with orders: [].
Return JSON only.`;

const DEFAULT_RESEARCH_GROUNDING_RULES = `---
GROUNDING RULES (critical - your output feeds live trading decisions):
- Today's date is {date}. Use the available tools and injected data before making current-market claims.
- For recent or time-sensitive claims about prices, liquidity, volume, news, social posts/tweets, filings, macro events, or market structure: search or query an available tool first.
- Justify every material claim with the retrieved source, timestamp, or data point. If you cannot verify something, say that it is unverified and do not use it as a reason to trade.
- Do not invent headlines, tweet/post authors, dates, prices, or catalysts. A short, honest report with uncertainty is better than a confident fabrication.
- Distinguish facts retrieved this run from your interpretation. Keep speculation clearly labeled.`;

// Example injected data previews — mirrors the runtime sections and can be overridden from Settings.
const INJECTED_DATA_EXAMPLES: Record<string, { label: string; preview: string }> = {
  includeWalletOverview: {
    label: "Portfolio Overview",
    preview: `=== PORTFOLIO OVERVIEW ===
Started: $1,000.00 | Now: $1,072.50 | Net PnL: $72.50
Runs: 24 | Trades: 18 | Fees: $3.40`,
  },
  includePerformanceStats: {
    label: "Performance Stats",
    preview: `=== PERFORMANCE STATS ===
{
  "runCount": 24,
  "tradeCount": 18,
  "totalFeesUsd": 3.40,
  "firstPortfolioUsd": 1000,
  "currentPortfolioUsd": 1072.50,
  "netPnlUsd": 72.50
}`,
  },
  includeBotRanking: {
    label: "Bot Rankings",
    preview: `=== BOT RANKINGS ===
1. Alpha Momentum: $142.30 net PnL
2. Swing Macro: $72.50 net PnL
3. This Bot: $45.20 net PnL`,
  },
  includePastTrades: {
    label: "Past Trades",
    preview: `=== RECENT TRADES (last 10) ===
BUY BTCUSDT qty=0.0012 @ 68450 -> success
SELL ETHUSDT qty=0.15 @ 2410 -> success
BUY SOLUSDT qty=2.5 @ 142.80 -> success`,
  },
};

const buildResearchGroundingPreview = () => ({
  label: "Grounding Rules",
  preview: DEFAULT_RESEARCH_GROUNDING_RULES,
});

const TRADER_NON_NEGOTIABLE_PREVIEW = {
  label: "Non-Negotiable Constraints",
  preview: `---
HARD RULES:
- Buy only symbols verified this turn with binance_symbol_lookup.
- BUY: stopLossPrice < currentPrice and takeProfitPrice > currentPrice. SELL: both null.
- No valid trade: return hold with orders: [].
- Final answer: one TradingDecision JSON object.`,
};

const ALWAYS_INJECTED_TRADER: { label: string; preview: string }[] = [
  {
    label: "Research Output",
    preview: `=== UPSTREAM RESEARCH (phase 1 analysis) ===
[The full output from the research agent will appear here.]`,
  },
  {
    label: "Session",
    preview: `=== SESSION ===
Bot: My Strategy (#32) | Model: xAI grok-4.3
Mode: testnet | Venue: Binance Spot | Frequency: every 30min
Budget: $1,000.00 - you must stay within this allocation`,
  },
  {
    label: "Execution Rules",
    preview: `=== EXECUTION RULES ===
Order caps: OFF
Max drawdown kill: OFF
Allowed types: MARKET, LIMIT`,
  },
  {
    label: "Wallet",
    preview: `=== WALLET ===
Total: $1,072.50
USDT: 500.00 free ($500.00)
USDC: 250.20 free ($250.20)
BTC: 0.0012 free ($82.14)
ETH: 0.15 free ($361.50)`,
  },
  {
    label: "Trading Scope",
    preview: `=== TRADING SCOPE ===
You may trade any authorized stable-quoted spot pair available on Binance.`,
  },
  TRADER_NON_NEGOTIABLE_PREVIEW,
];

export type Prompt = {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  promptNumber: number;
  latestVersionId: string | null;
  latestBody: string | null;
  latestVersionCreatedAt: string | null;
  lastUsedAt: string | null;
};

export type TraderPrompt = {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  promptNumber: number;
  latestVersionId: string | null;
  latestBody: string | null;
  latestVersionCreatedAt: string | null;
  lastUsedAt: string | null;
};

export type Model = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

export type AppSettings = {
  agentDefaults: {
    research: {
      provider: "xai" | "nous" | "openai" | "anthropic" | "huggingface" | "google" | "mistral";
      modelProfileId: string | null;
      prompt: { mode: "new" | "saved"; versionId: string | null };
    };
    trader: {
      provider: "xai" | "nous" | "openai" | "anthropic" | "huggingface" | "google" | "mistral";
      modelProfileId: string | null;
      prompt: { mode: "new" | "saved"; versionId: string | null };
    };
    runtime: {
      venue: "binance" | "binance-testnet";
      frequencyMinutes: number;
      budgetUsdt: number;
      symbolScope: "selected" | "all";
      execution: {
        enabled: boolean;
        maxDrawdownEnabled: boolean;
        allowMarketOrders: boolean;
        allowLimitOrders: boolean;
        maxOrdersPerRun: number;
        maxNotionalPerOrderUsd: number;
        minCashReserveUsd: number;
        maxDrawdownPct: number;
      };
    };
  };
  featureToggles: {
    promptLab: boolean;
    sentiment: boolean;
    signals: boolean;
    researchLab: boolean;
    promptLibrary: boolean;
  };
  promptRuntime: {
    researchGroundingRules: string;
    injectedDataTemplates: {
      researchGrounding: { label: string; preview: string };
      traderResearchOutput: { label: string; preview: string };
      traderSession: { label: string; preview: string };
      traderExecutionRules: { label: string; preview: string };
      traderWallet: { label: string; preview: string };
      traderTradingScope: { label: string; preview: string };
      traderNonNegotiable: { label: string; preview: string };
      includeWalletOverview: { label: string; preview: string };
      includePerformanceStats: { label: string; preview: string };
      includeBotRanking: { label: string; preview: string };
      includePastTrades: { label: string; preview: string };
    };
  };
};

const FALLBACK_XAI_MODELS: Model[] = [
  { id: "fallback:xai:grok-4.3", name: "xAI grok-4.3", provider: "xai", model: "grok-4.3" },
  { id: "fallback:xai:grok-3", name: "xAI grok-3", provider: "xai", model: "grok-3" },
  { id: "fallback:xai:grok-3-fast", name: "xAI grok-3-fast", provider: "xai", model: "grok-3-fast" },
  { id: "fallback:xai:grok-3-mini", name: "xAI grok-3-mini", provider: "xai", model: "grok-3-mini" },
  { id: "fallback:xai:grok-3-mini-fast", name: "xAI grok-3-mini-fast", provider: "xai", model: "grok-3-mini-fast" },
];

export const FALLBACK_MODELS: Model[] = [
  ...FALLBACK_XAI_MODELS,
  { id: "fallback:openai:gpt-4.1", name: "OpenAI GPT-4.1", provider: "openai", model: "gpt-4.1" },
  { id: "fallback:openai:gpt-4.1-mini", name: "OpenAI GPT-4.1 mini", provider: "openai", model: "gpt-4.1-mini" },
  { id: "fallback:google:gemini-3-pro-preview", name: "Google Gemini 3 Pro Preview", provider: "google", model: "gemini-3-pro-preview" },
  { id: "fallback:google:gemini-3-flash-preview", name: "Google Gemini 3 Flash Preview", provider: "google", model: "gemini-3-flash-preview" },
  { id: "fallback:mistral:mistral-large-2512", name: "Mistral Large 3", provider: "mistral", model: "mistral-large-2512" },
  { id: "fallback:mistral:mistral-medium-latest", name: "Mistral Medium latest", provider: "mistral", model: "mistral-medium-latest" },
  { id: "fallback:anthropic:claude-sonnet-4-5", name: "Anthropic Claude Sonnet 4.5", provider: "anthropic", model: "claude-sonnet-4-5" },
  { id: "fallback:anthropic:claude-haiku-4-5", name: "Anthropic Claude Haiku 4.5", provider: "anthropic", model: "claude-haiku-4-5" },
  { id: "fallback:huggingface:deepseek-ai/DeepSeek-R1:fastest", name: "Hugging Face DeepSeek R1 fastest", provider: "huggingface", model: "deepseek-ai/DeepSeek-R1:fastest" },
  { id: "fallback:nous:nousresearch/hermes-4-70b", name: "Nous Hermes 4 70B", provider: "nous", model: "nousresearch/hermes-4-70b" },
];

export const PROVIDER_ORDER = ["xai", "openai", "anthropic", "google", "mistral", "huggingface", "nous"];

export const DEFAULT_APP_SETTINGS: AppSettings = {
  agentDefaults: {
    research: { provider: "xai", modelProfileId: null, prompt: { mode: "saved", versionId: null } },
    trader: { provider: "xai", modelProfileId: null, prompt: { mode: "saved", versionId: null } },
    runtime: {
      venue: "binance-testnet",
      frequencyMinutes: 30,
      budgetUsdt: 1000,
      symbolScope: "all",
      execution: {
        enabled: false,
        maxDrawdownEnabled: false,
        allowMarketOrders: true,
        allowLimitOrders: true,
        maxOrdersPerRun: 3,
        maxNotionalPerOrderUsd: 250,
        minCashReserveUsd: 25,
        maxDrawdownPct: 10
      }
    }
  },
  featureToggles: {
    promptLab: false,
    sentiment: false,
    signals: false,
    researchLab: false,
    promptLibrary: false
  },
  promptRuntime: {
    researchGroundingRules: DEFAULT_RESEARCH_GROUNDING_RULES,
    injectedDataTemplates: {
      researchGrounding: buildResearchGroundingPreview(),
      traderResearchOutput: ALWAYS_INJECTED_TRADER[0]!,
      traderSession: ALWAYS_INJECTED_TRADER[1]!,
      traderExecutionRules: ALWAYS_INJECTED_TRADER[2]!,
      traderWallet: ALWAYS_INJECTED_TRADER[3]!,
      traderTradingScope: ALWAYS_INJECTED_TRADER[4]!,
      traderNonNegotiable: ALWAYS_INJECTED_TRADER[5]!,
      includeWalletOverview: INJECTED_DATA_EXAMPLES.includeWalletOverview,
      includePerformanceStats: INJECTED_DATA_EXAMPLES.includePerformanceStats,
      includeBotRanking: INJECTED_DATA_EXAMPLES.includeBotRanking,
      includePastTrades: INJECTED_DATA_EXAMPLES.includePastTrades
    }
  }
};

export const renderRuntimeTemplate = (template: string) =>
  template.replaceAll("{date}", new Date().toISOString().slice(0, 10));

export const mergeAppSettings = (data?: Partial<AppSettings> | null): AppSettings => {
  const defaults = DEFAULT_APP_SETTINGS;
  const templates = data?.promptRuntime?.injectedDataTemplates;
  return {
    ...defaults,
    ...data,
    agentDefaults: {
      ...defaults.agentDefaults,
      ...data?.agentDefaults,
      research: {
        ...defaults.agentDefaults.research,
        ...data?.agentDefaults?.research,
        prompt: {
          ...defaults.agentDefaults.research.prompt,
          ...data?.agentDefaults?.research?.prompt
        }
      },
      trader: {
        ...defaults.agentDefaults.trader,
        ...data?.agentDefaults?.trader,
        prompt: {
          ...defaults.agentDefaults.trader.prompt,
          ...data?.agentDefaults?.trader?.prompt
        }
      },
      runtime: {
        ...defaults.agentDefaults.runtime,
        ...data?.agentDefaults?.runtime,
        execution: {
          ...defaults.agentDefaults.runtime.execution,
          ...data?.agentDefaults?.runtime?.execution
        }
      }
    },
    featureToggles: {
      ...defaults.featureToggles,
      ...data?.featureToggles
    },
    promptRuntime: {
      ...defaults.promptRuntime,
      ...data?.promptRuntime,
      injectedDataTemplates: {
        ...defaults.promptRuntime.injectedDataTemplates,
        ...templates
      }
    }
  };
};

export const pickBestModel = (models: Model[]): Model | undefined => {
  const checks: Array<(m: Model) => boolean> = [
    (m) => /grok-4\.?3/i.test(m.model),
    (m) => /reasoning/i.test(m.model) && !/fast|mini/i.test(m.model),
    (m) => /reasoning/i.test(m.model),
    (m) => !/mini|fast|beta/i.test(m.model),
    () => true,
  ];
  for (const check of checks) {
    const match = models.find(check);
    if (match) return match;
  }
  return models[0];
};

export type BotSetup = {
  id: string;
  name: string;
  promptVersionId: string;
  traderPromptVersionId: string | null;
  modelProfileId: string;
  modelProvider: string;
  traderModelProfileId: string | null;
  traderModelProvider: string | null;
  promptConfig: {
    modules: {
      includeCurrentPositions: boolean;
      includePastTrades: boolean;
      pastTradesLookback: number;
      includePerformanceStats: boolean;
      includeBotRanking: boolean;
      includeWalletOverview: boolean;
    };
  };
  runtimeConfig: {
    venue: "binance" | "binance-testnet";
    frequencyMinutes: number;
    mode: "testnet" | "live";
    budgetUsdt?: number;
    symbolScope: "selected" | "all";
    contextSymbols: string[];
    execution: {
      enabled: boolean;
      maxDrawdownEnabled: boolean;
      allowMarketOrders: boolean;
      allowLimitOrders: boolean;
      maxOrdersPerRun: number;
      maxNotionalPerOrderUsd: number;
      minCashReserveUsd: number;
      maxDrawdownPct: number;
    };
  };
};

export type SymbolResponse = {
  label: string;
  symbols: string[];
};

export type VenueBalance = {
  configured: boolean;
  connected: boolean;
  checkedAt: string;
  error: string | null;
  totalFreeUsdt: number;
  allocatedUsdt: number;
  availableUsdt: number;
};

export type BotFormModalProps = {
  mode: "create" | "edit";
  botId?: string;
  onClose: () => void;
  onSuccess: () => void;
};

const slugify = (value: string) =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

export const uniqueSlug = (value: string) => `${slugify(value) || "bot"}-${Date.now().toString(36)}`;

export const uniqueSymbols = (symbols: string[]) =>
  Array.from(new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean)));

export const VENUE_LABELS: Record<string, string> = {
  "binance": "Binance",
  "binance-testnet": "Binance Testnet",
};

export const FREQUENCY_OPTIONS = [
  { value: "1", label: "Every 1 min" },
  { value: "5", label: "Every 5 min" },
  { value: "15", label: "Every 15 min" },
  { value: "30", label: "Every 30 min" },
  { value: "60", label: "Every 1 hour" },
  { value: "240", label: "Every 4 hours" },
  { value: "720", label: "Every 12 hours" },
  { value: "1440", label: "Every 24 hours" },
];

export const buildDefaultState = () => {
  return {
    name: "",
    // Research prompt
    researchStrategy: "existing" as "new" | "existing",
    existingPromptVersionId: "",
    newResearchName: "",
    newResearchBody: "",
    // Trader prompt
    traderStrategy: "existing" as "new" | "existing",
    existingTraderVersionId: "",
    newTraderName: "",
    newTraderBody: "",
    // Per-phase model selection
    researchModelProfileId: "",
    traderModelProfileId: "",
    // Runtime (kept for backward compat during submit)
    modelProfileId: "",
    venue: "binance-testnet" as "binance" | "binance-testnet",
    frequencyMinutes: "30",
    budgetUsdt: 1000,
    symbolScope: "all" as "selected" | "all",
    contextSymbols: [] as string[],
    execution: {
      enabled: false,
      maxDrawdownEnabled: false,
      allowMarketOrders: true,
      allowLimitOrders: true,
      maxOrdersPerRun: 3,
      maxNotionalPerOrderUsd: 250,
      minCashReserveUsd: 25,
      maxDrawdownPct: 10
    },
    promptConfig: {
      modules: {
        includeCurrentPositions: true,
        includePastTrades: false,
        pastTradesLookback: 10,
        includePerformanceStats: false,
        includeBotRanking: false,
        includeWalletOverview: false
      }
    }
  };
};
