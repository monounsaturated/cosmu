// module: Settings console constants, types, and pure helpers. No React — imported by settings-console.tsx.
import { DEFAULT_INJECTED_DATA_TEMPLATES, DEFAULT_RESEARCH_GROUNDING_RULES, type ResearchDataSource } from "@cosmu/shared";

export type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

export type PromptProfile = {
  id: string;
  name: string;
  latestVersionId: string | null;
  latestBody: string | null;
  promptNumber: number;
  latestVersionCreatedAt?: string | null;
  createdAt?: string;
  lastUsedAt?: string | null;
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
      [K in keyof typeof DEFAULT_INJECTED_DATA_TEMPLATES]: { label: string; preview: string };
    };
  };
};

export type Diagnostics = {
  webEnv?: { apiBaseUrl?: string; hasKey?: boolean };
  backend?: {
    modelProviderKeys?: Record<string, boolean>;
    tradingAccountKeys?: Record<string, boolean>;
    scheduler?: {
      enabled: boolean;
      loopStarted: boolean;
      tickRunning: boolean;
      intervalMs: number;
      lastTickAt: string | null;
      lastFinishedAt: string | null;
      lastDueBotCount: number;
      lastResultCount: number;
      lastError: string | null;
    };
    automation?: {
      guardian?: {
        enabled: boolean;
        running: boolean;
        tickRunning: boolean;
        intervalMs: number;
        reconciled: boolean;
      };
    };
  };
  backendError?: string;
};

export const PROVIDERS = ["xai", "openai", "anthropic", "google", "mistral", "huggingface", "nous"] as const;

const PROVIDER_LABELS: Record<string, string> = {
  xai: "xAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  huggingface: "Hugging Face",
  google: "Google",
  mistral: "Mistral",
  nous: "Nous"
};

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
    injectedDataTemplates: DEFAULT_INJECTED_DATA_TEMPLATES
  }
};

export const mergeAppSettings = (data?: Partial<AppSettings> | null): AppSettings => {
  const defaults = DEFAULT_APP_SETTINGS;
  const agentDefaults = data?.agentDefaults;
  return {
    ...defaults,
    ...data,
    agentDefaults: {
      ...defaults.agentDefaults,
      ...agentDefaults,
      research: {
        ...defaults.agentDefaults.research,
        ...agentDefaults?.research,
        prompt: {
          ...defaults.agentDefaults.research.prompt,
          ...agentDefaults?.research?.prompt
        }
      },
      trader: {
        ...defaults.agentDefaults.trader,
        ...agentDefaults?.trader,
        prompt: {
          ...defaults.agentDefaults.trader.prompt,
          ...agentDefaults?.trader?.prompt
        }
      },
      runtime: {
        ...defaults.agentDefaults.runtime,
        ...agentDefaults?.runtime,
        execution: {
          ...defaults.agentDefaults.runtime.execution,
          ...agentDefaults?.runtime?.execution
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
        ...data?.promptRuntime?.injectedDataTemplates
      }
    }
  };
};

export const DATA_SOURCE_KINDS: ResearchDataSource["kind"][] = [
  "market",
  "news",
  "web",
  "social",
  "weather",
  "astro",
  "tradingview",
  "csv",
  "custom_api",
  "ibkr",
  "polymarket"
];

export const DATA_SOURCE_PRESETS: Array<{
  name: string;
  kind: ResearchDataSource["kind"];
  config: Record<string, unknown>;
}> = [
  { name: "Yahoo Finance quotes", kind: "market", config: { provider: "yahoo", status: "planned" } },
  { name: "Binance market data", kind: "market", config: { provider: "binance", status: "planned" } },
  { name: "Finance news feed", kind: "news", config: { provider: "rss", status: "planned" } },
  { name: "Macro calendar", kind: "custom_api", config: { provider: "fred_or_calendar", status: "planned" } },
  { name: "Polymarket context", kind: "polymarket", config: { provider: "polymarket", status: "planned" } }
];

export const providerLabel = (provider: string) => PROVIDER_LABELS[provider] ?? (provider || "custom");

export const formatDiagnosticTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString() : "never";

export const promptOptions = (prompts: PromptProfile[], label: "Research" | "Trader") =>
  prompts
    .filter((prompt) => Boolean(prompt.latestVersionId))
    .sort((a, b) => {
      if (a.lastUsedAt && b.lastUsedAt) return b.lastUsedAt.localeCompare(a.lastUsedAt);
      if (a.lastUsedAt && !b.lastUsedAt) return -1;
      if (!a.lastUsedAt && b.lastUsedAt) return 1;
      return (b.latestVersionCreatedAt ?? b.createdAt ?? "").localeCompare(a.latestVersionCreatedAt ?? a.createdAt ?? "");
    })
    .map((prompt) => ({
      id: prompt.latestVersionId!,
      label: `${label} Prompt #${prompt.promptNumber} - ${prompt.name}`
    }));

export const PRODUCT_SWITCHES: Array<{
  key: keyof AppSettings["featureToggles"];
  label: string;
  description: string;
}> = [
  { key: "promptLab", label: "Prompt Lab", description: "Prompt history, experiments, and advisor surface." },
  { key: "sentiment", label: "Sentiment", description: "Market sentiment dashboards and topic scoring." },
  { key: "signals", label: "Signals", description: "Raw observations converted into standardized signals." },
  { key: "researchLab", label: "Research lab", description: "Venue-scoped experiments, data sources, and candidates." },
  { key: "promptLibrary", label: "Prompt library", description: "Version history and prompt inspection." }
];
