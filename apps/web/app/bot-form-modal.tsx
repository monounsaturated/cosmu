"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const ALL_SYMBOLS_TOKEN = "__ALL__";

const DEFAULT_PROMPT_BODY = `You are the trading decision engine for one autonomous spot bot.

Return only valid JSON matching the provided schema.

Objectives:
- manage the current spot portfolio prudently
- prefer clear, high-conviction actions
- if conditions are unclear, choose hold with no orders

Rules:
- venue is Binance spot
- mode is supplied in runtime context and must be respected implicitly by the operator, not mentioned in the output
- do not invent balances, prices, or symbols
- only propose orders for symbols that can plausibly trade against USDT
- keep the order list lean
- every order must include a concise rationale`;

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
  { id: "fallback:xai:grok-beta", name: "xAI grok-beta", provider: "xai", model: "grok-beta" },
  { id: "fallback:xai:grok-2", name: "xAI grok-2", provider: "xai", model: "grok-2" }
];

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
  defaultBotNumber?: number;
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

const buildDefaultState = (defaultBotNumber: number) => {
  const defaultName = "";
  return {
    name: defaultName,
    promptStrategy: "new" as "new" | "existing",
    existingPromptVersionId: "",
    newPromptName: `Bot #${defaultBotNumber} Prompt`,
    newPromptBody: DEFAULT_PROMPT_BODY,
    modelProfileId: "",
    venue: "binance-testnet" as "binance" | "binance-testnet",
    frequencyMinutes: "15",
    budgetUsdt: 100,
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

export function BotFormModal({ mode, botId, defaultBotNumber = 1, onClose, onSuccess }: BotFormModalProps) {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
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
  const [formData, setFormData] = useState(buildDefaultState(defaultBotNumber));

  // Prompt body view/edit state
  const [promptBody, setPromptBody] = useState<string | null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [showBodyEditor, setShowBodyEditor] = useState(false);
  const [editedBody, setEditedBody] = useState("");
  const [savingVersion, setSavingVersion] = useState(false);
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

  const promptOptions = useMemo(
    () =>
      prompts
        .filter((prompt) => Boolean(prompt.latestVersionId))
        .map((prompt) => ({
          id: prompt.latestVersionId!,
          promptId: prompt.id,
          createdAt: prompt.latestVersionCreatedAt ?? prompt.createdAt,
          body: prompt.latestBody ?? "",
          label: `Prompt #${prompt.promptNumber} - ${prompt.name}`
        }))
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    [prompts]
  );

  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toUpperCase();
    const source = query ? symbols.filter((s) => s.includes(query)) : symbols;
    return source.slice(0, 120);
  }, [symbolSearch, symbols]);

  // Resilient fetch helper — returns data or null without throwing, with optional error message
  const safeFetch = async <T,>(url: string): Promise<{ data: T | null; error: string | null }> => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) {
        console.warn(`[bot-form] ${url} → ${res.status}`);
        let errorMsg = `HTTP ${res.status}`;
        try {
          const errData = await res.json();
          if (errData.error) errorMsg = errData.error;
        } catch (_) {}
        return { data: null, error: errorMsg };
      }
      return { data: (await res.json()) as T, error: null };
    } catch (e) {
      console.warn(`[bot-form] ${url} failed:`, e);
      return { data: null, error: e instanceof Error ? e.message : String(e) };
    } finally {
      clearTimeout(timeout);
    }
  };

  // Force sync models from xAI API
  const syncModels = async () => {
    setIsSyncing(true);
    setError(null);
    try {
      const res = await fetch("/api/internal/catalog/sync?force=true", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      if (!res.ok) {
        throw new Error(`Sync failed: ${res.status}`);
      }
      const result = await res.json();
      console.log("[bot-form] Model sync result:", result);

      // Refresh models list
      const modelsRes = await safeFetch<Model[]>("/api/models");
      if (modelsRes.data && modelsRes.data.length > 0) {
        setModels(modelsRes.data);
        setError(null);
      } else if (modelsRes.error) {
        setError(`Sync completed, but could not load models: ${modelsRes.error}`);
      } else {
        setError("Sync completed but no models available. Check XAI_API_KEY configuration.");
      }
    } catch (e) {
      console.error("[bot-form] Sync failed:", e);
      setError(`Failed to sync models: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSyncing(false);
    }
  };

  // Client-side Binance fallback — public endpoint, no API key needed
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

    if (!needsCreation) {
      return id;
    }

    const selected = availableModels.find((m) => m.id === id);
    if (!selected) {
      throw new Error("Selected model is invalid");
    }

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

  // Initial data load — each fetch is independent so one failure doesn't block others
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setDataLoaded(false);
      setError(null);

      const [promptsRes, modelsRes, symbolsRes, botRes] = await Promise.all([
        safeFetch<Prompt[]>("/api/prompts"),
        safeFetch<Model[]>("/api/models"),
        safeFetch<SymbolResponse>("/api/venues/binance/symbols"),
        mode === "edit" && botId ? safeFetch<BotSetup>(`/api/bots/${botId}`) : Promise.resolve({ data: null, error: null })
      ]);

      if (cancelled) return;

      const promptsData = promptsRes.data;
      const modelsData = modelsRes.data;
      const symbolsData = symbolsRes.data;
      const botData = botRes.data;

      if (promptsData) setPrompts(promptsData);
      if (modelsData && modelsData.length > 0) setModels(modelsData);

      // Symbols: try backend first, fall back to direct Binance call
      let resolvedSymbols: string[] = symbolsData?.symbols ?? [];
      if (resolvedSymbols.length === 0) {
        resolvedSymbols = await fetchSymbolsDirect();
      }
      if (resolvedSymbols.length > 0) setSymbols(resolvedSymbols);

      if (cancelled) return;

      const errors: string[] = [];
      let errorMessage = "";

      if (!modelsData || modelsData.length === 0) errors.push("models");
      if (resolvedSymbols.length === 0) errors.push("symbols");
      if (mode === "edit" && botId && !botData) errors.push("bot config");

      if (errors.length) {
        if (errors.includes("models")) {
          if (modelsRes.error) {
            errorMessage = `Could not load AI models. Server reported: "${modelsRes.error}". Check database connectivity and API keys.`;
          } else {
            errorMessage = "Could not load AI models. The API may be unreachable or XAI_API_KEY is not configured. Try clicking 'Sync Models from xAI' below.";
          }
        } else {
          errorMessage = `Could not load: ${errors.join(", ")}. Check API connectivity or retry.`;
        }
        setError(errorMessage);
      }

      if (mode === "edit" && botData) {
        const setup = botData;
        const botModel = (modelsData ?? []).find((m) => m.id === setup.modelProfileId);
        if (botModel?.provider) setSelectedProvider(botModel.provider);

        const mergedVenue: "binance" | "binance-testnet" =
          setup.runtimeConfig.venue === "binance-testnet" || setup.runtimeConfig.mode === "testnet"
            ? "binance-testnet"
            : "binance";

        setFormData({
          name: setup.name,
          promptStrategy: "existing",
          existingPromptVersionId: setup.promptVersionId,
          newPromptName: `${setup.name} Prompt`,
          newPromptBody: DEFAULT_PROMPT_BODY,
          modelProfileId: setup.modelProfileId,
          promptConfig: setup.promptConfig,
          venue: mergedVenue,
          frequencyMinutes: String(setup.runtimeConfig.frequencyMinutes),
          budgetUsdt: setup.runtimeConfig.budgetUsdt ?? 100,
          symbolScope: setup.runtimeConfig.symbolScope,
          contextSymbols: setup.runtimeConfig.contextSymbols,
          execution: setup.runtimeConfig.execution
        });
      } else if (modelsData && modelsData.length > 0) {
        const firstModel = modelsData.find((m) => m.provider === selectedProvider) ?? modelsData[0];
        if (firstModel) {
          setSelectedProvider(firstModel.provider);
          setFormData((cur) => ({
            ...cur,
            modelProfileId: cur.modelProfileId || firstModel.id
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

  // Sync model selection when provider changes
  useEffect(() => {
    if (!formData.modelProfileId && availableModels[0]?.id) {
      setFormData((cur) => ({ ...cur, modelProfileId: availableModels[0]!.id }));
    }
  }, [availableModels, formData.modelProfileId]);

  // Close pairs dropdown on outside click
  useEffect(() => {
    if (!pairsOpen) return;
    const handle = (e: MouseEvent) => {
      if (pairsRef.current && !pairsRef.current.contains(e.target as Node)) {
        setPairsOpen(false);
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [pairsOpen]);

  // Auto-select first prompt
  useEffect(() => {
    if (!formData.existingPromptVersionId && promptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingPromptVersionId: promptOptions[0]!.id }));
    }
  }, [promptOptions, formData.existingPromptVersionId]);

  // Load prompt body when a saved prompt is selected
  useEffect(() => {
    if (formData.promptStrategy !== "existing" || !formData.existingPromptVersionId) {
      setPromptBody(null);
      setShowBodyEditor(false);
      return;
    }

    const selectedPrompt = promptOptions.find((option) => option.id === formData.existingPromptVersionId);
    setLoadingBody(false);
    setShowBodyEditor(false);
    setPromptBody(selectedPrompt?.body ?? null);
    setEditedBody(selectedPrompt?.body ?? "");
  }, [formData.existingPromptVersionId, formData.promptStrategy, promptOptions]);

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

  const handleSaveNewVersion = async () => {
    setSavingVersion(true);
    setError(null);
    try {
      const selectedPrompt = prompts.find((prompt) => prompt.latestVersionId === formData.existingPromptVersionId);
      const fallbackName = selectedPrompt?.name ?? `Prompt ${Date.now()}`;
      const res = await fetch("/api/prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fallbackName,
          slug: uniqueSlug(fallbackName),
          initialBody: editedBody
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to save prompt");

      const promptsRes = await fetch("/api/prompts");
      const promptsData = await promptsRes.json();
      setPrompts(promptsData);
      setFormData((cur) => ({ ...cur, existingPromptVersionId: data.promptVersionId }));
      setShowBodyEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save updated prompt");
    } finally {
      setSavingVersion(false);
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

  const updateModule = (key: keyof typeof formData.promptConfig.modules, value: boolean | number) => {
    setFormData((cur) => ({
      ...cur,
      promptConfig: {
        ...cur.promptConfig,
        modules: { ...cur.promptConfig.modules, [key]: value }
      }
    }));
  };

  const resolvePromptVersionId = async () => {
    if (formData.promptStrategy === "existing") {
      if (!formData.existingPromptVersionId) throw new Error("Choose a saved prompt");
      return formData.existingPromptVersionId;
    }

    const res = await fetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: formData.newPromptName.trim(),
        slug: uniqueSlug(formData.newPromptName),
        initialBody: formData.newPromptBody.trim()
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
      if (formData.promptStrategy === "new" && !formData.newPromptName.trim()) throw new Error("Prompt name is required");
      if (formData.promptStrategy === "new" && !formData.newPromptBody.trim()) throw new Error("Prompt body is required");
      if (formData.symbolScope === "selected" && formData.contextSymbols.length === 0) {
        throw new Error("Select at least one pair, or choose All Pairs");
      }

      const promptVersionId = await resolvePromptVersionId();
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

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-content-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{mode === "create" ? "Create Bot" : "Rename Bot"}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        {loading ? (
          <p className="muted">Loading configuration…</p>
        ) : (
          <form className="modal-form" onSubmit={handleSubmit}>

            {/* ── Bot name ── */}
            <div className="form-section">
              <h3>Bot</h3>
              <div className="form-row">
                <label>
                  Name (Optional)
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="My Strategy"
                  />
                </label>
              </div>
            </div>

            {/* ── Prompt ── */}
            <div className="form-section">
              <h3>Prompt</h3>

              <details className="prompt-howto">
                <summary>How to write a good prompt</summary>
                <div className="prompt-howto-body">
                  <p>The prompt is the <strong>entire brain</strong> of the bot. Everything the model knows about your strategy comes from here. The system automatically appends your wallet balance, execution rules, and any injected data modules you tick below.</p>

                  <h4>What to include</h4>
                  <ul>
                    <li><strong>Strategy &amp; style</strong> — scalping, swing, macro rotation, DCA, mean reversion…</li>
                    <li><strong>Risk tolerance</strong> — how tight/loose SL/TP, max drawdown you accept</li>
                    <li><strong>Entry/exit logic</strong> — what signals or conditions trigger a buy or sell</li>
                    <li><strong>Position sizing</strong> — e.g. &quot;never more than 10% of portfolio in one trade&quot;</li>
                    <li><strong>Market bias</strong> — e.g. &quot;bullish on ETH ecosystem, cautious on memes&quot;</li>
                    <li><strong>Hold behavior</strong> — when to hold and not trade (the bot defaults to hold)</li>
                  </ul>

                  <h4>What NOT to include</h4>
                  <ul>
                    <li><strong>Market prices</strong> — the model fetches them from its own knowledge</li>
                    <li><strong>Wallet balances</strong> — injected automatically at every run</li>
                    <li><strong>SL/TP rules</strong> — enforced by the system (every buy has mandatory SL/TP)</li>
                    <li><strong>JSON format instructions</strong> — the response format is locked by schema</li>
                    <li><strong>Execution constraints</strong> — max orders, notional limits etc. are injected separately</li>
                  </ul>

                  <h4>Example prompts</h4>
                  <div className="prompt-example">
                    <span className="prompt-example-tag">Aggressive Scalper</span>
                    <pre>{`You are an aggressive BTC/ETH scalper on Binance spot.
Look for short-term momentum: breakouts, volume spikes, support/resistance bounces.
Enter fast, exit fast. Target 1-3% moves. SL tight at 1.5% below entry.
If no clear setup exists in the next few minutes, hold.
Max 2 simultaneous positions. Prefer market orders for speed.`}</pre>
                  </div>
                  <div className="prompt-example">
                    <span className="prompt-example-tag">Swing Holder</span>
                    <pre>{`You are a patient swing trader focusing on top-20 altcoins.
Look for multi-day trends: higher lows, RSI divergences, volume confirmation.
Enter on pullbacks to support. TP at 8-15%, SL at 5%.
Hold existing winners unless trend structure breaks.
Avoid trading during low-volume weekends.
Keep 50% in USDT as dry powder for dips.`}</pre>
                  </div>
                  <div className="prompt-example">
                    <span className="prompt-example-tag">Macro Rotation</span>
                    <pre>{`You manage a diversified spot portfolio across BTC, ETH, SOL, and stablecoins.
Rotate allocation based on macro momentum: risk-on → more alts, risk-off → more USDT.
Rebalance weekly, not daily. Only trade when allocation drifts >10% from target.
Target allocation: 40% BTC, 25% ETH, 15% SOL, 20% USDT.
Keep trades small — max 5% of portfolio per order.`}</pre>
                  </div>
                </div>
              </details>

              <div className="segmented-control">
                <button
                  type="button"
                  className={`segmented-option ${formData.promptStrategy === "new" ? "segmented-option-active" : ""}`}
                  onClick={() => setFormData({ ...formData, promptStrategy: "new" })}
                >
                  New prompt
                </button>
                <button
                  type="button"
                  className={`segmented-option ${formData.promptStrategy === "existing" ? "segmented-option-active" : ""}`}
                  onClick={() => setFormData({ ...formData, promptStrategy: "existing" })}
                  disabled={promptOptions.length === 0}
                >
                  Saved prompt
                </button>
              </div>

              {formData.promptStrategy === "new" ? (
                <div className="form-grid">
                  <div className="form-row">
                    <label>
                      Prompt Name
                      <input
                        type="text"
                        value={formData.newPromptName}
                        onChange={(e) => setFormData({ ...formData, newPromptName: e.target.value })}
                        placeholder="Bot #1 Prompt"
                        required
                      />
                    </label>
                  </div>
                  <div className="form-row" style={{ gridColumn: "1 / -1" }}>
                    <label>
                      Prompt Body
                      <textarea
                        value={formData.newPromptBody}
                        onChange={(e) => setFormData({ ...formData, newPromptBody: e.target.value })}
                        rows={10}
                        required
                      />
                    </label>
                  </div>
                </div>
              ) : (
                <>
                  <div className="form-row">
                    <label>
                      Prompt
                      <select
                        value={formData.existingPromptVersionId}
                        onChange={(e) => setFormData({ ...formData, existingPromptVersionId: e.target.value })}
                        required
                      >
                        <option value="">Select a prompt</option>
                        {promptOptions.map((p) => (
                          <option key={p.id} value={p.id}>{p.label}</option>
                        ))}
                      </select>
                    </label>
                  </div>

                  {formData.existingPromptVersionId && (
                    <div className="prompt-body-panel">
                      <div className="prompt-body-header">
                        <span className="field-help">Prompt body</span>
                        {!showBodyEditor && (
                          <button
                            type="button"
                            className="btn btn-xs"
                            onClick={() => setShowBodyEditor(true)}
                            disabled={loadingBody || !promptBody}
                          >
                            {loadingBody ? "Loading…" : "Edit"}
                          </button>
                        )}
                      </div>

                      {showBodyEditor ? (
                        <>
                          <textarea
                            className="prompt-body-textarea"
                            value={editedBody}
                            onChange={(e) => setEditedBody(e.target.value)}
                            rows={10}
                          />
                          <div className="prompt-body-actions">
                            <button
                              type="button"
                              className="btn"
                              onClick={() => { setShowBodyEditor(false); setEditedBody(promptBody ?? ""); }}
                              disabled={savingVersion}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={handleSaveNewVersion}
                              disabled={savingVersion || !editedBody.trim()}
                            >
                              {savingVersion ? "Saving…" : "Save as new prompt"}
                            </button>
                          </div>
                        </>
                      ) : (
                        <pre className="prompt-body-preview">
                          {loadingBody ? "Loading…" : (promptBody ?? "—")}
                        </pre>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* ── Model & Runtime ── */}
            <div className="form-section">
              <div className="section-header">
                <h3>Model &amp; Runtime</h3>
                {dataLoaded && models.length === 0 && (
                  <button
                    type="button"
                    className="btn btn-xs"
                    onClick={() => setLoadTrigger((n) => n + 1)}
                  >
                    ↻ Retry
                  </button>
                )}
              </div>
              <div className="form-grid">
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
                        <option value="">{dataLoaded ? "Not available" : "Loading…"}</option>
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
                        <option value="">{dataLoaded ? "Not available" : "Loading…"}</option>
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
                      {loadingBalance ? "…" : `${venueBalance.totalFreeUsdt.toFixed(2)} USDT on account · ${venueBalance.availableUsdt.toFixed(2)} available`}
                    </span>
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
                    Max USDT this bot can use. It must sell positions to free up budget.
                  </span>
                </div>

                <div className="form-row">
                  <label>
                    Frequency
                    <select
                      value={formData.frequencyMinutes}
                      onChange={(e) => setFormData({ ...formData, frequencyMinutes: e.target.value })}
                      disabled={mode !== "create"}
                    >
                      <option value="1">Every 1 min</option>
                      <option value="5">Every 5 min</option>
                      <option value="15">Every 15 min</option>
                      <option value="30">Every 30 min</option>
                      <option value="60">Every 60 min</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>

            {/* ── Injected Data ── */}
            <div className="form-section">
              <h3>Injected Data</h3>
              <p className="field-help">
                Tick the live data modules appended to the prompt at every run.
              </p>

              <div className="modules-grid">
                {[
                  { key: "includeCurrentPositions" as const, label: "Current positions & prices" },
                  { key: "includeWalletOverview" as const, label: "Wallet overview (start vs now)" },
                  { key: "includePerformanceStats" as const, label: "Performance stats" },
                  { key: "includePastTrades" as const, label: "Past trades" },
                  { key: "includeBotRanking" as const, label: "Ranking vs other bots" }
                ].map(({ key, label }) => (
                  <label key={key} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={formData.promptConfig.modules[key] as boolean}
                      onChange={(e) => updateModule(key, e.target.checked)}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>

              {formData.promptConfig.modules.includePastTrades && (
                <div className="form-row" style={{ maxWidth: 200 }}>
                  <label>
                    Lookback (trades)
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={formData.promptConfig.modules.pastTradesLookback}
                      onChange={(e) => updateModule("pastTradesLookback", Number(e.target.value))}
                    />
                  </label>
                </div>
              )}
            </div>

            {/* ── Authorized Pairs ── */}
            <div className="form-section">
              <h3>Authorized Pairs</h3>

              <div className="pairs-picker" ref={pairsRef}>
                <input
                  type="text"
                  className="pairs-search"
                  value={symbolSearch}
                  onChange={(e) => setSymbolSearch(e.target.value)}
                  placeholder="Search BTC, ETH, XMR…"
                  onFocus={() => setPairsOpen(true)}
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
                      <span>All Binance Pairs</span>
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
                    {symbols.length === 0 && !dataLoaded && (
                      <p className="pairs-empty">Loading pairs…</p>
                    )}
                    {symbols.length === 0 && dataLoaded && (
                      <p className="pairs-empty">
                        Pairs unavailable.{" "}
                        <button
                          type="button"
                          className="inline-retry"
                          onClick={() => setLoadTrigger((n) => n + 1)}
                        >
                          Retry
                        </button>
                      </p>
                    )}
                  </div>
                )}
              </div>

              {formData.symbolScope === "selected" && formData.contextSymbols.length > 0 && (
                <div className="selected-symbols">
                  {formData.contextSymbols.map((symbol) => (
                    <button
                      key={symbol}
                      type="button"
                      className="badge badge-button"
                      onClick={() => toggleSymbol(symbol)}
                    >
                      {symbol} ×
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* ── Execution Rules ── */}
            <div className="form-section">
              <h3>Execution Rules</h3>
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
                  <div className="form-error-actions" style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="btn btn-small"
                      onClick={syncModels}
                      disabled={isSyncing}
                      title="Fetch latest models from xAI API"
                    >
                      {isSyncing ? "Syncing…" : "↻ Sync Models from xAI"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-small"
                      onClick={() => window.location.reload()}
                      disabled={isSyncing}
                    >
                      Reload Page
                    </button>
                  </div>
                )}
                {error.includes("models") && !error.includes("Server reported") && (
                  <p className="field-help" style={{ marginTop: "0.5rem" }}>
                    Tip: Ensure XAI_API_KEY is set in your environment and the API server is running.
                  </p>
                )}
              </div>
            )}

            <div className="form-actions">
              <button type="button" className="btn" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving
                  ? mode === "create" ? "Creating…" : "Saving…"
                  : mode === "create" ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
