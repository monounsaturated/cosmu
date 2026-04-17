"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const ALL_SYMBOLS_TOKEN = "__ALL__";

const DEFAULT_RESEARCH_PROMPT = `You are an autonomous crypto spot trading engine on Binance.

Your goal is to grow the portfolio by finding high-conviction trading opportunities.

Strategy:
- Analyze your current positions, wallet balance, and market conditions
- Look for momentum plays, breakouts, and strong trends in established coins
- Focus on top cryptocurrencies (BTC, ETH, SOL, BNB, XRP) and promising mid-caps
- Enter positions when you see clear setups with favorable risk/reward
- Set stop-loss 3-5% below entry, take-profit 8-15% above entry
- If no clear opportunity exists right now, hold and wait

Position management:
- Keep at least 30% of budget in USDT as dry powder
- Maximum 3 open positions at any time
- Cut losers quickly, let winners run

Rules:
- Do not invent balances, prices, or symbols
- Only propose orders for symbols that can plausibly trade against USDT
- Keep the order list lean — quality over quantity
- Every order must include a concise rationale`;

const DEFAULT_TRADER_PROMPT = `You are the execution stage (phase 2) for one autonomous Binance USDT spot bot.

Inputs (in the user message):
- UPSTREAM RESEARCH: qualitative thesis from phase 1 — symbols may be informal; normalize to valid *USDT pairs only when you place orders.
- SESSION / EXECUTION RULES / WALLET / AUTHORIZED PAIRS: hard facts — never contradict them.
- LIVE MARKET PRICES: authoritative reference for sizing stops and limits on buys.

Output: exactly one JSON object (no markdown fences, no prose) matching TradingDecision:
- mode: one of "rebalance" | "enter" | "exit" | "hold" | "adjust". Use "hold" when there is no defensible trade.
- rationaleSummary: <=600 chars, decision-grade summary.
- globalRationale: <=4000 chars tying research to orders or explaining why you are flat.
- confidence: number in [0,1].
- timeHorizon: short string or null.
- orders: array (<= max orders/run from rules). Each order: symbol, side buy|sell, type market|limit, quantity (>0), limitPrice (null unless limit), stopLossPrice, takeProfitPrice, rationale.
- targetAllocations: usually [].

Order logic:
- BUY: every buy MUST set stopLossPrice strictly below the live reference price for that symbol and takeProfitPrice strictly above. Omit trades you cannot justify with the given prices.
- SELL: set stopLossPrice and takeProfitPrice to null.
- Respect authorized pair list when present; otherwise any Binance USDT spot pair is allowed if grounded in research + prices.
- Stay within wallet + execution caps; prefer fewer, higher-conviction orders over many small ones.
- If research conflicts with prices, scope, or risk limits, prefer mode hold with orders: [].`;

// Example injected data previews — matches the exact format produced by prompt-context.ts
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
  includePastTrades: {
    label: "Past Trades",
    preview: `=== RECENT TRADES (last 10) ===
BUY BTCUSDT qty=0.0012 @ 68450 → success
SELL ETHUSDT qty=0.15 @ 2410 → success
BUY SOLUSDT qty=2.5 @ 142.80 → success`,
  },
  includeBotRanking: {
    label: "Bot Rankings",
    preview: `=== BOT RANKINGS ===
1. Alpha Momentum: $142.30 net PnL
2. Swing Macro: $72.50 net PnL
3. This Bot: $45.20 net PnL`,
  },
};

// Always-injected sections for the trader prompt (non-toggleable)
const ALWAYS_INJECTED_TRADER: { label: string; preview: string }[] = [
  {
    label: "Upstream Research",
    preview: `=== UPSTREAM RESEARCH (phase 1 analysis) ===
[The full output from the research agent will appear here — your creative analysis, symbol mentions, thesis, etc.]`,
  },
  {
    label: "Session",
    preview: `=== SESSION ===
Bot: My Strategy (#32) | Model: xAI grok-3
Mode: testnet | Venue: Binance Spot | Frequency: every 30min
Budget: $1,000.00 — you must stay within this allocation`,
  },
  {
    label: "Execution Rules",
    preview: `=== EXECUTION RULES ===
Rules enforced: YES
Max orders/run: 3 | Max notional/order: 250 USDT
Cash reserve (untouchable): 25 USDT
Allowed types: MARKET, LIMIT`,
  },
  {
    label: "Wallet",
    preview: `=== WALLET ===
Total: $1,072.50
USDT: 750.20 free ($750.20)
BTC: 0.0012 free ($82.14)
ETH: 0.15 free ($361.50)`,
  },
  {
    label: "Live Market Prices",
    preview: `=== LIVE MARKET PRICES (for execution) ===
Use these reference prices for stopLossPrice / takeProfitPrice on buys.
BTCUSDT: 68450.00
ETHUSDT: 2410.00
SOLUSDT: 142.80`,
  },
  {
    label: "Trading Scope",
    preview: `=== TRADING SCOPE ===
You may trade ANY USDT spot pair available on Binance. Pick your symbols based on your own analysis.`,
  },
];

// Always-injected sections for the research prompt (non-toggleable)
const ALWAYS_INJECTED_RESEARCH: { label: string; preview: string }[] = [
  {
    label: "Session",
    preview: `=== SESSION ===
Bot: My Strategy (#32) | Model: xAI grok-3
Mode: testnet | Venue: Binance Spot | Frequency: every 30min
Budget: $1,000.00 — you must stay within this allocation`,
  },
  {
    label: "Wallet",
    preview: `=== WALLET ===
Total: $1,072.50
USDT: 750.20 free ($750.20)
BTC: 0.0012 free ($82.14)
ETH: 0.15 free ($361.50)`,
  },
  {
    label: "Trading Scope",
    preview: `=== TRADING SCOPE ===
You may trade ANY USDT spot pair available on Binance. Pick your symbols based on your own analysis.`,
  },
];

type Prompt = {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  promptNumber: number;
  latestVersionId: string | null;
  latestBody: string | null;
  latestVersionCreatedAt: string | null;
};

type FormatterVersion = {
  id: string;
  venue: string;
  promptType: string;
  version: number;
  body: string;
  createdAt: string;
};

type Model = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

const FALLBACK_XAI_MODELS: Model[] = [
  { id: "fallback:xai:grok-3", name: "xAI grok-3", provider: "xai", model: "grok-3" },
  { id: "fallback:xai:grok-3-fast", name: "xAI grok-3-fast", provider: "xai", model: "grok-3-fast" },
  { id: "fallback:xai:grok-3-mini", name: "xAI grok-3-mini", provider: "xai", model: "grok-3-mini" },
  { id: "fallback:xai:grok-3-mini-fast", name: "xAI grok-3-mini-fast", provider: "xai", model: "grok-3-mini-fast" },
];

const pickBestModel = (models: Model[]): Model | undefined => {
  const checks: Array<(m: Model) => boolean> = [
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

type BotSetup = {
  id: string;
  name: string;
  promptVersionId: string;
  modelProfileId: string;
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
      allowMarketOrders: boolean;
      allowLimitOrders: boolean;
      maxOrdersPerRun: number;
      maxNotionalPerOrderUsd: number;
      minCashReserveUsd: number;
    };
  };
};

type SymbolResponse = {
  label: string;
  symbols: string[];
};

type BotFormModalProps = {
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

const uniqueSlug = (value: string) => `${slugify(value) || "bot"}-${Date.now().toString(36)}`;

const uniqueSymbols = (symbols: string[]) =>
  Array.from(new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean)));

const FREQUENCY_OPTIONS = [
  { value: "1", label: "Every 1 min" },
  { value: "5", label: "Every 5 min" },
  { value: "15", label: "Every 15 min" },
  { value: "30", label: "Every 30 min" },
  { value: "60", label: "Every 1 hour" },
  { value: "240", label: "Every 4 hours" },
  { value: "720", label: "Every 12 hours" },
  { value: "1440", label: "Every 24 hours" },
];

const buildDefaultState = () => {
  return {
    name: "",
    // Research prompt
    researchStrategy: "new" as "new" | "existing",
    existingPromptVersionId: "",
    newResearchName: "",
    newResearchBody: DEFAULT_RESEARCH_PROMPT,
    // Trader prompt
    traderStrategy: "new" as "new" | "existing",
    existingTraderVersionId: "",
    newTraderName: "",
    newTraderBody: DEFAULT_TRADER_PROMPT,
    // Model & runtime
    modelProfileId: "",
    venue: "binance-testnet" as "binance" | "binance-testnet",
    frequencyMinutes: "30",
    budgetUsdt: 1000,
    symbolScope: "all" as "selected" | "all",
    contextSymbols: [] as string[],
    execution: {
      enabled: false,
      allowMarketOrders: true,
      allowLimitOrders: true,
      maxOrdersPerRun: 3,
      maxNotionalPerOrderUsd: 250,
      minCashReserveUsd: 25
    },
    promptConfig: {
      modules: {
        includeCurrentPositions: true,
        includePastTrades: false,
        pastTradesLookback: 10,
        includePerformanceStats: true,
        includeBotRanking: false,
        includeWalletOverview: true
      }
    }
  };
};

// ── Injected Data Preview Component ─────────────────────────────────────
function InjectedPreviewBlock({ label, preview, alwaysOn }: { label: string; preview: string; alwaysOn?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="injected-block">
      <button
        type="button"
        className="injected-block-header"
        onClick={() => setOpen(!open)}
      >
        <span className="injected-block-label">
          {alwaysOn && <span className="injected-always-badge">always</span>}
          {label}
        </span>
        <span className="injected-block-chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="injected-block-preview">{preview}</pre>
      )}
    </div>
  );
}

// ── Prompt Section Component ────────────────────────────────────────────
function PromptSection({
  phase,
  phaseColor,
  strategy,
  onStrategyChange,
  promptOptions,
  selectedVersionId,
  onVersionChange,
  promptName,
  onNameChange,
  promptBody,
  onBodyChange,
  savedBody,
  showBodyEditor,
  onToggleEditor,
  editedBody,
  onEditedBodyChange,
  onSaveNewVersion,
  savingVersion,
  loadingBody,
  // Injected data
  alwaysInjected,
  optionalModules,
  activeModules,
  onToggleModule,
  pastTradesLookback,
  onLookbackChange,
}: {
  phase: "research" | "trader";
  phaseColor: string;
  strategy: "new" | "existing";
  onStrategyChange: (s: "new" | "existing") => void;
  promptOptions: { id: string; label: string; body: string }[];
  selectedVersionId: string;
  onVersionChange: (id: string) => void;
  promptName: string;
  onNameChange: (n: string) => void;
  promptBody: string;
  onBodyChange: (b: string) => void;
  savedBody: string | null;
  showBodyEditor: boolean;
  onToggleEditor: (v: boolean) => void;
  editedBody: string;
  onEditedBodyChange: (b: string) => void;
  onSaveNewVersion: () => void;
  savingVersion: boolean;
  loadingBody: boolean;
  alwaysInjected: { label: string; preview: string }[];
  optionalModules?: { key: string; label: string; preview: string }[];
  activeModules?: Record<string, boolean>;
  onToggleModule?: (key: string, value: boolean) => void;
  pastTradesLookback?: number;
  onLookbackChange?: (n: number) => void;
}) {
  const title = phase === "research" ? "Research Prompt" : "Trader Prompt";

  // Derive prompt number from selected option
  const selectedOption = promptOptions.find((p) => p.id === selectedVersionId);
  const promptLabel = strategy === "existing" && selectedOption
    ? selectedOption.label
    : promptName
      ? `${title} — ${promptName}`
      : title;

  return (
    <div className="form-section" style={{ borderLeft: `3px solid ${phaseColor}` }}>
      <h3 style={{ color: phaseColor }}>{promptLabel}</h3>

      <div className="segmented-control">
        <button
          type="button"
          className={`segmented-option ${strategy === "new" ? "segmented-option-active" : ""}`}
          onClick={() => onStrategyChange("new")}
        >
          New Prompt
        </button>
        <button
          type="button"
          className={`segmented-option ${strategy === "existing" ? "segmented-option-active" : ""}`}
          onClick={() => onStrategyChange("existing")}
          disabled={promptOptions.length === 0}
        >
          Saved Prompt
        </button>
      </div>

      {strategy === "new" ? (
        <div className="form-grid">
          <div className="form-row">
            <label>
              Prompt Name <span className="field-help">(optional)</span>
              <input
                type="text"
                value={promptName}
                onChange={(e) => onNameChange(e.target.value)}
                placeholder="Auto-generated if empty"
              />
            </label>
          </div>
          <div className="form-row" style={{ gridColumn: "1 / -1" }}>
            <label>Prompt Body</label>
            <div className="prompt-composer">
              <textarea
                className="prompt-composer-textarea"
                value={promptBody}
                onChange={(e) => onBodyChange(e.target.value)}
                rows={10}
                required
              />
              {/* Injected data separator + preview */}
              {alwaysInjected.length > 0 && (
                <div className="prompt-composer-injected">
                  <div className="injected-separator">
                    <span className="injected-separator-label">Injected Data (auto-appended at runtime)</span>
                  </div>
                  {alwaysInjected.map((item) => (
                    <InjectedPreviewBlock key={item.label} label={item.label} preview={item.preview} alwaysOn />
                  ))}
                  {optionalModules?.filter((m) => activeModules?.[m.key]).map((m) => (
                    <InjectedPreviewBlock key={m.key} label={m.label} preview={m.preview} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="form-row">
            <label>
              Prompt
              <select
                value={selectedVersionId}
                onChange={(e) => onVersionChange(e.target.value)}
                required
              >
                <option value="">Select a prompt</option>
                {promptOptions.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </label>
          </div>

          {selectedVersionId && (
            <div className="prompt-body-panel">
              <div className="prompt-body-header">
                <span className="field-help">Prompt body</span>
                {!showBodyEditor && (
                  <button
                    type="button"
                    className="btn btn-xs"
                    onClick={() => onToggleEditor(true)}
                    disabled={loadingBody || !savedBody}
                  >
                    {loadingBody ? "Loading..." : "Edit"}
                  </button>
                )}
              </div>

              {showBodyEditor ? (
                <>
                  <textarea
                    className="prompt-body-textarea"
                    value={editedBody}
                    onChange={(e) => onEditedBodyChange(e.target.value)}
                    rows={10}
                  />
                  <div className="prompt-body-actions">
                    <button
                      type="button"
                      className="btn"
                      onClick={() => { onToggleEditor(false); onEditedBodyChange(savedBody ?? ""); }}
                      disabled={savingVersion}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={onSaveNewVersion}
                      disabled={savingVersion || !editedBody.trim()}
                    >
                      {savingVersion ? "Saving..." : "Save as new prompt"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <pre className="prompt-body-preview">
                    {loadingBody ? "Loading..." : (savedBody ?? "\u2014")}
                  </pre>
                  {/* Injected data preview below saved prompt */}
                  {alwaysInjected.length > 0 && (
                    <div className="prompt-composer-injected">
                      <div className="injected-separator">
                        <span className="injected-separator-label">Injected Data (auto-appended at runtime)</span>
                      </div>
                      {alwaysInjected.map((item) => (
                        <InjectedPreviewBlock key={item.label} label={item.label} preview={item.preview} alwaysOn />
                      ))}
                      {optionalModules?.filter((m) => activeModules?.[m.key]).map((m) => (
                        <InjectedPreviewBlock key={m.key} label={m.label} preview={m.preview} />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}

      {/* Optional injected data modules (trader only) */}
      {optionalModules && optionalModules.length > 0 && (
        <div className="injected-data-section">
          <h4>Injected Data</h4>
          <p className="field-help">
            Tick modules to append live data to the trader prompt at every run. Toggle a module to preview how it appears.
          </p>
          <div className="modules-grid">
            <label className="checkbox-label" style={{ opacity: 0.6 }}>
              <input type="checkbox" checked disabled />
              <span>Wallet &amp; held positions <span className="field-help">(always included)</span></span>
            </label>
            {optionalModules.map((m) => (
              <label key={m.key} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={activeModules?.[m.key] ?? false}
                  onChange={(e) => onToggleModule?.(m.key, e.target.checked)}
                />
                <span>{m.label}</span>
              </label>
            ))}
          </div>

          {activeModules?.includePastTrades && pastTradesLookback !== undefined && (
            <div className="form-row" style={{ maxWidth: 200, marginTop: 8 }}>
              <label>
                Lookback (trades)
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={pastTradesLookback}
                  onChange={(e) => onLookbackChange?.(Number(e.target.value))}
                />
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function BotFormModal({ mode, botId, onClose, onSuccess }: BotFormModalProps) {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [formatterVersions, setFormatterVersions] = useState<FormatterVersion[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loading, setLoading] = useState(mode === "edit");
  const [dataLoaded, setDataLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadTrigger, setLoadTrigger] = useState(0);
  const [symbolSearch, setSymbolSearch] = useState("");
  const [pairsOpen, setPairsOpen] = useState(false);
  const pairsRef = useRef<HTMLDivElement>(null);
  const [selectedProvider, setSelectedProvider] = useState("xai");
  const [formData, setFormData] = useState(buildDefaultState());
  const [nextBotNumber, setNextBotNumber] = useState<number | null>(null);

  // Research prompt editor state
  const [researchSavedBody, setResearchSavedBody] = useState<string | null>(null);
  const [researchShowEditor, setResearchShowEditor] = useState(false);
  const [researchEditedBody, setResearchEditedBody] = useState("");
  const [researchSavingVersion, setResearchSavingVersion] = useState(false);

  // Trader prompt editor state
  const [traderSavedBody, setTraderSavedBody] = useState<string | null>(null);
  const [traderShowEditor, setTraderShowEditor] = useState(false);
  const [traderEditedBody, setTraderEditedBody] = useState("");
  const [traderSavingVersion, setTraderSavingVersion] = useState(false);

  const [isSyncing, setIsSyncing] = useState(false);
  const [venueBalance, setVenueBalance] = useState<{ totalFreeUsdt: number; allocatedUsdt: number; availableUsdt: number } | null>(null);
  const [loadingBalance, setLoadingBalance] = useState(false);

  const providerOptions = useMemo(() => {
    const fromApi = Array.from(new Set(models.map((m) => m.provider))).sort();
    return fromApi.length > 0 ? fromApi : ["xai"];
  }, [models]);

  const availableModels = useMemo(() => {
    const fromApi = models.filter((m) => m.provider === selectedProvider);
    if (fromApi.length > 0) return fromApi;
    if (selectedProvider === "xai") return FALLBACK_XAI_MODELS;
    return [];
  }, [models, selectedProvider]);

  // Research prompt options — "Default Prompt" always first, then by most recently used
  const researchPromptOptions = useMemo(() => {
    const opts = prompts
      .filter((prompt) => Boolean(prompt.latestVersionId))
      .map((prompt) => ({
        id: prompt.latestVersionId!,
        promptId: prompt.id,
        createdAt: prompt.latestVersionCreatedAt ?? prompt.createdAt,
        body: prompt.latestBody ?? "",
        label: `Research Prompt #${prompt.promptNumber} — ${prompt.name}`,
        isDefault: prompt.name.toLowerCase().includes("default")
      }));

    // Default prompt first, then most recently used
    return opts.sort((a, b) => {
      if (a.isDefault && !b.isDefault) return -1;
      if (!a.isDefault && b.isDefault) return 1;
      return b.createdAt.localeCompare(a.createdAt);
    });
  }, [prompts]);

  // Trader prompt options from formatter versions
  const traderPromptOptions = useMemo(() => {
    return formatterVersions.map((v) => ({
      id: v.id,
      label: `Trader Prompt #${v.version}`,
      body: v.body,
    }));
  }, [formatterVersions]);

  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toUpperCase();
    const source = query ? symbols.filter((s) => s.includes(query)) : symbols;
    return source.slice(0, 120);
  }, [symbolSearch, symbols]);

  const safeFetch = async <T,>(url: string): Promise<{ data: T | null; error: string | null }> => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) {
        let errorMsg = `HTTP ${res.status}`;
        try { const errData = await res.json(); if (errData.error) errorMsg = errData.error; } catch (_) {}
        return { data: null, error: errorMsg };
      }
      return { data: (await res.json()) as T, error: null };
    } catch (e) {
      return { data: null, error: e instanceof Error ? e.message : String(e) };
    } finally {
      clearTimeout(timeout);
    }
  };

  const syncModels = async () => {
    setIsSyncing(true);
    setError(null);
    try {
      const res = await fetch("/api/internal/catalog/sync?force=true", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      if (!res.ok) throw new Error(`Sync failed: ${res.status}`);
      const modelsRes = await safeFetch<Model[]>("/api/models");
      if (modelsRes.data && modelsRes.data.length > 0) {
        setModels(modelsRes.data);
        setError(null);
      } else {
        setError("Sync completed but no models available. Check XAI_API_KEY configuration.");
      }
    } catch (e) {
      setError(`Failed to sync models: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const fetchSymbolsDirect = async (): Promise<string[]> => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch("https://api.binance.com/api/v3/exchangeInfo", { signal: controller.signal });
      if (!res.ok) return [];
      const data = await res.json();
      return ((data.symbols ?? []) as Array<{ symbol: string; status: string; isSpotTradingAllowed: boolean; quoteAsset: string }>)
        .filter((s) => s.status === "TRADING" && s.isSpotTradingAllowed !== false && s.quoteAsset === "USDT")
        .map((s) => s.symbol)
        .sort();
    } catch {
      return [];
    } finally {
      clearTimeout(timeout);
    }
  };

  const resolveModelProfileId = async () => {
    const id = formData.modelProfileId;
    const needsCreation = id.startsWith("fallback:") || id.startsWith("live:");
    if (!needsCreation) return id;

    const selected = availableModels.find((m) => m.id === id);
    if (!selected) throw new Error("Selected model is invalid");

    const res = await fetch("/api/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: selected.name,
        provider: selected.provider,
        model: selected.model,
        settings: { temperature: 0.2 }
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Failed to create model profile");
    return data.id as string;
  };

  // Initial data load
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setDataLoaded(false);
      setError(null);

      const defaultVenue = formData.venue;

      const [promptsRes, modelsRes, symbolsRes, botRes, formatterRes] = await Promise.all([
        safeFetch<Prompt[]>("/api/prompts"),
        safeFetch<Model[]>("/api/models"),
        safeFetch<SymbolResponse>("/api/venues/binance/symbols"),
        mode === "edit" && botId ? safeFetch<BotSetup>(`/api/bots/${botId}`) : Promise.resolve({ data: null, error: null }),
        safeFetch<{ versions: FormatterVersion[] }>(`/api/settings/formatter-prompt/${defaultVenue}/versions`),
      ]);

      if (cancelled) return;

      if (promptsRes.data) {
        setPrompts(promptsRes.data);
        setNextBotNumber(promptsRes.data.length + 1);
      }
      if (modelsRes.data && modelsRes.data.length > 0) setModels(modelsRes.data);
      if (formatterRes.data?.versions) setFormatterVersions(formatterRes.data.versions);

      let resolvedSymbols: string[] = symbolsRes.data?.symbols ?? [];
      if (resolvedSymbols.length === 0) resolvedSymbols = await fetchSymbolsDirect();
      if (resolvedSymbols.length > 0) setSymbols(resolvedSymbols);

      if (cancelled) return;

      const errors: string[] = [];
      if (!modelsRes.data || modelsRes.data.length === 0) errors.push("models");
      if (resolvedSymbols.length === 0) errors.push("symbols");
      if (mode === "edit" && botId && !botRes.data) errors.push("bot config");

      if (errors.length) {
        if (errors.includes("models")) {
          setError(modelsRes.error
            ? `Could not load AI models: "${modelsRes.error}".`
            : "Could not load AI models. Try clicking 'Sync Models from xAI' below.");
        } else {
          setError(`Could not load: ${errors.join(", ")}. Check API connectivity.`);
        }
      }

      if (mode === "edit" && botRes.data) {
        const setup = botRes.data;
        const botModel = (modelsRes.data ?? []).find((m) => m.id === setup.modelProfileId);
        if (botModel?.provider) setSelectedProvider(botModel.provider);

        const mergedVenue: "binance" | "binance-testnet" =
          setup.runtimeConfig.venue === "binance-testnet" || setup.runtimeConfig.mode === "testnet"
            ? "binance-testnet"
            : "binance";

        setFormData({
          name: setup.name,
          researchStrategy: "existing",
          existingPromptVersionId: setup.promptVersionId,
          newResearchName: "",
          newResearchBody: DEFAULT_RESEARCH_PROMPT,
          traderStrategy: "existing",
          existingTraderVersionId: "",
          newTraderName: "",
          newTraderBody: DEFAULT_TRADER_PROMPT,
          modelProfileId: setup.modelProfileId,
          promptConfig: { ...setup.promptConfig },
          venue: mergedVenue,
          frequencyMinutes: String(setup.runtimeConfig.frequencyMinutes),
          budgetUsdt: setup.runtimeConfig.budgetUsdt ?? 1000,
          symbolScope: setup.runtimeConfig.symbolScope,
          contextSymbols: setup.runtimeConfig.contextSymbols,
          execution: setup.runtimeConfig.execution
        });
      } else if (modelsRes.data && modelsRes.data.length > 0) {
        const providerModels = modelsRes.data.filter((m) => m.provider === selectedProvider);
        const bestModel = pickBestModel(providerModels.length > 0 ? providerModels : modelsRes.data);
        if (bestModel) {
          setSelectedProvider(bestModel.provider);
          setFormData((cur) => ({
            ...cur,
            modelProfileId: cur.modelProfileId || bestModel.id,
            name: cur.name || "",
          }));
        }
      }

      setDataLoaded(true);
      setLoading(false);
    };

    load();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId, mode, loadTrigger]);

  // Set default bot name once we know the count
  useEffect(() => {
    if (mode === "create" && nextBotNumber && !formData.name) {
      setFormData((cur) => ({ ...cur, name: `Bot #${nextBotNumber}` }));
    }
  }, [nextBotNumber, mode, formData.name]);

  // Sync model selection when provider changes
  useEffect(() => {
    if (!formData.modelProfileId && availableModels.length > 0) {
      const best = pickBestModel(availableModels);
      if (best) setFormData((cur) => ({ ...cur, modelProfileId: best.id }));
    }
  }, [availableModels, formData.modelProfileId]);

  // Close pairs dropdown on outside click
  useEffect(() => {
    if (!pairsOpen) return;
    const handle = (e: MouseEvent) => {
      if (pairsRef.current && !pairsRef.current.contains(e.target as Node)) setPairsOpen(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [pairsOpen]);

  // Auto-select first research prompt
  useEffect(() => {
    if (!formData.existingPromptVersionId && researchPromptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingPromptVersionId: researchPromptOptions[0]!.id }));
    }
  }, [researchPromptOptions, formData.existingPromptVersionId]);

  // Auto-select first trader prompt
  useEffect(() => {
    if (!formData.existingTraderVersionId && traderPromptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingTraderVersionId: traderPromptOptions[0]!.id }));
    }
  }, [traderPromptOptions, formData.existingTraderVersionId]);

  // Load research prompt body when saved prompt selected
  useEffect(() => {
    if (formData.researchStrategy !== "existing" || !formData.existingPromptVersionId) {
      setResearchSavedBody(null);
      setResearchShowEditor(false);
      return;
    }
    const selected = researchPromptOptions.find((o) => o.id === formData.existingPromptVersionId);
    setResearchSavedBody(selected?.body ?? null);
    setResearchEditedBody(selected?.body ?? "");
    setResearchShowEditor(false);
  }, [formData.existingPromptVersionId, formData.researchStrategy, researchPromptOptions]);

  // Load trader prompt body when saved prompt selected
  useEffect(() => {
    if (formData.traderStrategy !== "existing" || !formData.existingTraderVersionId) {
      setTraderSavedBody(null);
      setTraderShowEditor(false);
      return;
    }
    const selected = traderPromptOptions.find((o) => o.id === formData.existingTraderVersionId);
    setTraderSavedBody(selected?.body ?? null);
    setTraderEditedBody(selected?.body ?? "");
    setTraderShowEditor(false);
  }, [formData.existingTraderVersionId, formData.traderStrategy, traderPromptOptions]);

  // Fetch formatter versions when venue changes
  useEffect(() => {
    let cancelled = false;
    safeFetch<{ versions: FormatterVersion[] }>(`/api/settings/formatter-prompt/${formData.venue}/versions`)
      .then((res) => { if (!cancelled && res.data?.versions) setFormatterVersions(res.data.versions); });
    return () => { cancelled = true; };
  }, [formData.venue]);

  // Fetch venue balance when venue changes
  useEffect(() => {
    let cancelled = false;
    setLoadingBalance(true);
    setVenueBalance(null);
    fetch(`/api/venues/${formData.venue}/balance`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (!cancelled && data) setVenueBalance(data); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingBalance(false); });
    return () => { cancelled = true; };
  }, [formData.venue]);

  const handleSaveResearchVersion = async () => {
    setResearchSavingVersion(true);
    setError(null);
    try {
      const res = await fetch("/api/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "", slug: "", initialBody: researchEditedBody })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to save prompt");

      const promptsRes = await fetch("/api/prompts");
      setPrompts(await promptsRes.json());
      setFormData((cur) => ({ ...cur, existingPromptVersionId: data.promptVersionId }));
      setResearchShowEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save prompt");
    } finally {
      setResearchSavingVersion(false);
    }
  };

  const handleSaveTraderVersion = async () => {
    setTraderSavingVersion(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/formatter-prompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formatterPrompts: {
            [formData.venue]: traderEditedBody,
            // Keep other venue unchanged
            ...(formData.venue === "binance"
              ? { "binance-testnet": formatterVersions[0]?.body ?? "" }
              : { binance: "" })
          }
        })
      });
      if (!res.ok) throw new Error("Failed to save trader prompt");

      // Refresh versions
      const versionsRes = await safeFetch<{ versions: FormatterVersion[] }>(`/api/settings/formatter-prompt/${formData.venue}/versions`);
      if (versionsRes.data?.versions) {
        setFormatterVersions(versionsRes.data.versions);
        if (versionsRes.data.versions[0]) {
          setFormData((cur) => ({ ...cur, existingTraderVersionId: versionsRes.data!.versions[0].id }));
        }
      }
      setTraderShowEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save trader prompt");
    } finally {
      setTraderSavingVersion(false);
    }
  };

  const toggleSymbol = (symbol: string) => {
    if (formData.symbolScope === "all") return;
    setFormData((cur) => ({
      ...cur,
      contextSymbols: cur.contextSymbols.includes(symbol)
        ? cur.contextSymbols.filter((s) => s !== symbol)
        : [...cur.contextSymbols, symbol]
    }));
  };

  const updateModule = (key: string, value: boolean) => {
    setFormData((cur) => ({
      ...cur,
      promptConfig: {
        ...cur.promptConfig,
        modules: { ...cur.promptConfig.modules, [key]: value }
      }
    }));
  };

  const resolveResearchPromptVersionId = async () => {
    if (formData.researchStrategy === "existing") {
      if (!formData.existingPromptVersionId) throw new Error("Choose a research prompt");
      return formData.existingPromptVersionId;
    }
    const res = await fetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: formData.newResearchName.trim(),
        slug: uniqueSlug(formData.newResearchName || "research"),
        initialBody: formData.newResearchBody.trim()
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Failed to create prompt");
    return data.promptVersionId as string;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      if (!formData.modelProfileId) throw new Error("Choose a model");
      if (formData.researchStrategy === "new" && !formData.newResearchBody.trim()) throw new Error("Research prompt body is required");
      if (formData.symbolScope === "selected" && formData.contextSymbols.length === 0) {
        throw new Error("Select at least one pair, or choose All Pairs");
      }

      // Save trader prompt if it's new
      if (formData.traderStrategy === "new" && formData.newTraderBody.trim()) {
        await fetch("/api/settings/formatter-prompt", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            formatterPrompts: {
              [formData.venue]: formData.newTraderBody.trim(),
              ...(formData.venue === "binance"
                ? { "binance-testnet": formatterVersions[0]?.body ?? DEFAULT_TRADER_PROMPT }
                : { binance: formatterVersions[0]?.body ?? DEFAULT_TRADER_PROMPT })
            }
          })
        });
      }

      const promptVersionId = await resolveResearchPromptVersionId();
      const modelProfileId = await resolveModelProfileId();
      const contextSymbols =
        formData.symbolScope === "all" ? [ALL_SYMBOLS_TOKEN] : uniqueSymbols(formData.contextSymbols);

      if (mode === "create") {
        const res = await fetch("/api/bots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: formData.name.trim(),
            slug: uniqueSlug(formData.name),
            promptVersionId,
            modelProfileId,
            promptConfig: formData.promptConfig,
            runtimeConfig: {
              venue: formData.venue,
              frequencyMinutes: Number(formData.frequencyMinutes),
              mode: formData.venue === "binance-testnet" ? "testnet" : "live",
              assetClass: "spot",
              budgetUsdt: formData.budgetUsdt,
              symbolScope: formData.symbolScope,
              execution: formData.execution,
              contextSymbols
            }
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Failed to create bot");
      } else {
        const res = await fetch(`/api/bots/${botId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: formData.name.trim() })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Failed to update bot");
      }

      onSuccess();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to save bot");
    } finally {
      setSaving(false);
    }
  };

  // Build optional module list for trader prompt
  const optionalModules = Object.entries(INJECTED_DATA_EXAMPLES).map(([key, val]) => ({
    key,
    label: val.label,
    preview: val.preview,
  }));

  const activeModules: Record<string, boolean> = {
    includeWalletOverview: formData.promptConfig.modules.includeWalletOverview,
    includePerformanceStats: formData.promptConfig.modules.includePerformanceStats,
    includePastTrades: formData.promptConfig.modules.includePastTrades,
    includeBotRanking: formData.promptConfig.modules.includeBotRanking,
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content modal-content-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{mode === "create" ? "Create Bot" : "Rename Bot"}</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        {loading ? (
          <p className="muted">Loading configuration...</p>
        ) : (
          <form className="modal-form" onSubmit={handleSubmit}>

            {/* ── Bot Name ── */}
            <div className="form-section">
              <div className="form-row">
                <label>
                  Bot Name
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder={nextBotNumber ? `Bot #${nextBotNumber}` : "My Strategy"}
                  />
                </label>
              </div>
            </div>

            {/* ── Core Settings ── */}
            <div className="form-section">
              <div className="section-header">
                <h3>Core Settings</h3>
                {dataLoaded && models.length === 0 && (
                  <button type="button" className="btn btn-xs" onClick={() => setLoadTrigger((n) => n + 1)}>
                    Retry
                  </button>
                )}
              </div>
              <div className="form-grid form-grid-3col">
                {/* Row 1: Provider, Model, Frequency */}
                <div className="form-row">
                  <label>
                    Provider
                    <select
                      value={providerOptions.length > 0 ? selectedProvider : ""}
                      onChange={(e) => {
                        setSelectedProvider(e.target.value);
                        setFormData((cur) => ({ ...cur, modelProfileId: "" }));
                      }}
                      disabled={mode !== "create" || providerOptions.length === 0}
                    >
                      {providerOptions.length === 0 ? (
                        <option value="">{dataLoaded ? "Not available" : "Loading..."}</option>
                      ) : (
                        providerOptions.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))
                      )}
                    </select>
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Model
                    <select
                      value={formData.modelProfileId}
                      onChange={(e) => setFormData({ ...formData, modelProfileId: e.target.value })}
                      required
                      disabled={mode !== "create" || availableModels.length === 0}
                    >
                      {availableModels.length === 0 ? (
                        <option value="">{dataLoaded ? "Not available" : "Loading..."}</option>
                      ) : (
                        <>
                          <option value="">Select a model</option>
                          {availableModels.map((m) => (
                            <option key={m.id} value={m.id}>{m.name} ({m.model})</option>
                          ))}
                        </>
                      )}
                    </select>
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Frequency
                    <select
                      value={formData.frequencyMinutes}
                      onChange={(e) => setFormData({ ...formData, frequencyMinutes: e.target.value })}
                      disabled={mode !== "create"}
                    >
                      {FREQUENCY_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </label>
                </div>

                {/* Row 2: Venue, Authorized Pairs, Budget */}
                <div className="form-row">
                  <label>
                    Venue
                    <select
                      value={formData.venue}
                      onChange={(e) => setFormData({ ...formData, venue: e.target.value as "binance" | "binance-testnet" })}
                      disabled={mode !== "create"}
                    >
                      <option value="binance-testnet">Binance Testnet</option>
                      <option value="binance">Binance</option>
                    </select>
                  </label>
                  {venueBalance && (
                    <span className="venue-balance">
                      {loadingBalance ? "..." : `${venueBalance.totalFreeUsdt.toFixed(2)} USDT on account`}
                    </span>
                  )}
                </div>

                <div className="form-row">
                  <label>
                    Authorized Pairs
                    <div className="pairs-picker" ref={pairsRef}>
                      <input
                        type="text"
                        className="pairs-search"
                        value={formData.symbolScope === "all" ? "" : symbolSearch}
                        onChange={(e) => setSymbolSearch(e.target.value)}
                        placeholder={formData.symbolScope === "all"
                          ? `All ${formData.venue === "binance" ? "Binance" : "Testnet"} Pairs`
                          : formData.contextSymbols.length > 0
                            ? `${formData.contextSymbols.length} pairs selected`
                            : "Search pairs..."}
                        onFocus={() => setPairsOpen(true)}
                        disabled={mode !== "create"}
                      />
                      {pairsOpen && (
                        <div className="pairs-dropdown">
                          <label className="pairs-row pairs-row-all">
                            <input
                              type="checkbox"
                              checked={formData.symbolScope === "all"}
                              onChange={(e) =>
                                setFormData({
                                  ...formData,
                                  symbolScope: e.target.checked ? "all" : "selected",
                                  contextSymbols: e.target.checked ? [] : formData.contextSymbols
                                })
                              }
                            />
                            <span>All {formData.venue === "binance" ? "Binance" : "Testnet"} Pairs</span>
                          </label>
                          {filteredSymbols.map((symbol) => (
                            <label
                              key={symbol}
                              className={`pairs-row ${formData.symbolScope === "all" ? "pairs-row-disabled" : ""}`}
                            >
                              <input
                                type="checkbox"
                                checked={formData.contextSymbols.includes(symbol)}
                                onChange={() => toggleSymbol(symbol)}
                                disabled={formData.symbolScope === "all"}
                              />
                              <span>{symbol}</span>
                            </label>
                          ))}
                          {filteredSymbols.length === 0 && symbols.length > 0 && (
                            <p className="pairs-empty">No match</p>
                          )}
                        </div>
                      )}
                    </div>
                  </label>
                  {formData.symbolScope === "selected" && formData.contextSymbols.length > 0 && (
                    <div className="selected-symbols">
                      {formData.contextSymbols.map((symbol) => (
                        <button key={symbol} type="button" className="badge badge-button" onClick={() => toggleSymbol(symbol)}>
                          {symbol} &times;
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="form-row">
                  <label>
                    Budget (USDT)
                    <input
                      type="number"
                      min={10}
                      step={10}
                      value={formData.budgetUsdt}
                      onChange={(e) => setFormData({ ...formData, budgetUsdt: Math.max(10, Number(e.target.value)) })}
                      disabled={mode !== "create"}
                    />
                  </label>
                  <span className="field-help">
                    Max USDT this bot can use.
                  </span>
                </div>
              </div>
            </div>

            {/* ── Research Prompt ── */}
            <PromptSection
              phase="research"
              phaseColor="#60a5fa"
              strategy={formData.researchStrategy}
              onStrategyChange={(s) => setFormData({ ...formData, researchStrategy: s })}
              promptOptions={researchPromptOptions}
              selectedVersionId={formData.existingPromptVersionId}
              onVersionChange={(id) => setFormData({ ...formData, existingPromptVersionId: id })}
              promptName={formData.newResearchName}
              onNameChange={(n) => setFormData({ ...formData, newResearchName: n })}
              promptBody={formData.newResearchBody}
              onBodyChange={(b) => setFormData({ ...formData, newResearchBody: b })}
              savedBody={researchSavedBody}
              showBodyEditor={researchShowEditor}
              onToggleEditor={setResearchShowEditor}
              editedBody={researchEditedBody}
              onEditedBodyChange={setResearchEditedBody}
              onSaveNewVersion={handleSaveResearchVersion}
              savingVersion={researchSavingVersion}
              loadingBody={false}
              alwaysInjected={ALWAYS_INJECTED_RESEARCH}
            />

            {/* ── Trader Prompt ── */}
            <PromptSection
              phase="trader"
              phaseColor="#a78bfa"
              strategy={formData.traderStrategy}
              onStrategyChange={(s) => setFormData({ ...formData, traderStrategy: s })}
              promptOptions={traderPromptOptions}
              selectedVersionId={formData.existingTraderVersionId}
              onVersionChange={(id) => setFormData({ ...formData, existingTraderVersionId: id })}
              promptName={formData.newTraderName}
              onNameChange={(n) => setFormData({ ...formData, newTraderName: n })}
              promptBody={formData.newTraderBody}
              onBodyChange={(b) => setFormData({ ...formData, newTraderBody: b })}
              savedBody={traderSavedBody}
              showBodyEditor={traderShowEditor}
              onToggleEditor={setTraderShowEditor}
              editedBody={traderEditedBody}
              onEditedBodyChange={setTraderEditedBody}
              onSaveNewVersion={handleSaveTraderVersion}
              savingVersion={traderSavingVersion}
              loadingBody={false}
              alwaysInjected={ALWAYS_INJECTED_TRADER}
              optionalModules={optionalModules}
              activeModules={activeModules}
              onToggleModule={updateModule}
              pastTradesLookback={formData.promptConfig.modules.pastTradesLookback}
              onLookbackChange={(n) => setFormData((cur) => ({
                ...cur,
                promptConfig: { ...cur.promptConfig, modules: { ...cur.promptConfig.modules, pastTradesLookback: n } }
              }))}
            />

            {/* ── Deterministic Settings ── */}
            <div className="form-section">
              <h3>Deterministic Settings</h3>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={formData.execution.enabled}
                  onChange={(e) =>
                    setFormData({ ...formData, execution: { ...formData.execution, enabled: e.target.checked } })
                  }
                />
                <span>Enable execution rules</span>
              </label>
              <p className="field-help">When off, only venue tradability and wallet sanity checks apply.</p>

              <div className="checkbox-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.execution.allowMarketOrders}
                    onChange={(e) =>
                      setFormData({ ...formData, execution: { ...formData.execution, allowMarketOrders: e.target.checked } })
                    }
                    disabled={!formData.execution.enabled}
                  />
                  <span>Market orders</span>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.execution.allowLimitOrders}
                    onChange={(e) =>
                      setFormData({ ...formData, execution: { ...formData.execution, allowLimitOrders: e.target.checked } })
                    }
                    disabled={!formData.execution.enabled}
                  />
                  <span>Limit orders</span>
                </label>
              </div>

              <div className="form-grid">
                <div className="form-row">
                  <label>
                    Max orders / run
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={formData.execution.maxOrdersPerRun}
                      onChange={(e) =>
                        setFormData({ ...formData, execution: { ...formData.execution, maxOrdersPerRun: Number(e.target.value) } })
                      }
                      disabled={!formData.execution.enabled}
                    />
                  </label>
                </div>
                <div className="form-row">
                  <label>
                    Max notional / order (USD)
                    <input
                      type="number"
                      min={1}
                      value={formData.execution.maxNotionalPerOrderUsd}
                      onChange={(e) =>
                        setFormData({ ...formData, execution: { ...formData.execution, maxNotionalPerOrderUsd: Number(e.target.value) } })
                      }
                      disabled={!formData.execution.enabled}
                    />
                  </label>
                </div>
                <div className="form-row">
                  <label>
                    Min cash reserve (USD)
                    <input
                      type="number"
                      min={0}
                      value={formData.execution.minCashReserveUsd}
                      onChange={(e) =>
                        setFormData({ ...formData, execution: { ...formData.execution, minCashReserveUsd: Number(e.target.value) } })
                      }
                      disabled={!formData.execution.enabled}
                    />
                  </label>
                </div>
              </div>
            </div>

            {error && (
              <div className="form-error">
                <p>{error}</p>
                {error.includes("models") && (
                  <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button type="button" className="btn btn-small" onClick={syncModels} disabled={isSyncing}>
                      {isSyncing ? "Syncing..." : "Sync Models from xAI"}
                    </button>
                    <button type="button" className="btn btn-small" onClick={() => window.location.reload()} disabled={isSyncing}>
                      Reload Page
                    </button>
                  </div>
                )}
              </div>
            )}

            <div className="form-actions">
              <button type="button" className="btn" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving
                  ? mode === "create" ? "Creating..." : "Saving..."
                  : mode === "create" ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
