"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PRE_PROMPT_PRESET_DESCRIPTIONS } from "@cosmu/shared";

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
  versions: { id: string; version: number; createdAt: string }[];
};

type Model = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

type BotSetup = {
  id: string;
  name: string;
  promptVersionId: string;
  modelProfileId: string;
  promptConfig: {
    preset: "minimal" | "performance" | "competitive" | "full-context";
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
    venue: "binance";
    frequencyMinutes: number;
    mode: "testnet" | "live";
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
  const defaultName = `Bot #${defaultBotNumber}`;
  return {
    name: defaultName,
    promptStrategy: "new" as "new" | "existing",
    existingPromptVersionId: "",
    newPromptName: `${defaultName} Prompt`,
    newPromptBody: DEFAULT_PROMPT_BODY,
    modelProfileId: "",
    venue: "binance" as const,
    frequencyMinutes: "15",
    mode: "testnet" as "testnet" | "live",
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
      preset: "minimal" as "minimal" | "performance" | "competitive" | "full-context",
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

  const providerOptions = useMemo(
    () => Array.from(new Set(models.map((m) => m.provider))).sort(),
    [models]
  );

  const availableModels = useMemo(
    () => models.filter((m) => m.provider === selectedProvider),
    [models, selectedProvider]
  );

  const promptOptions = useMemo(
    () =>
      prompts
        .flatMap((prompt) =>
          [...prompt.versions]
            .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
            .map((version) => ({
              id: version.id,
              promptId: prompt.id,
              createdAt: version.createdAt,
              label: `${prompt.name} v${version.version}`
            }))
        )
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    [prompts]
  );

  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toUpperCase();
    const source = query ? symbols.filter((s) => s.includes(query)) : symbols;
    return source.slice(0, 120);
  }, [symbolSearch, symbols]);

  // Resilient fetch helper — returns data or null without throwing
  const safeFetch = async <T,>(url: string): Promise<T | null> => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) {
        console.warn(`[bot-form] ${url} → ${res.status}`);
        return null;
      }
      return (await res.json()) as T;
    } catch (e) {
      console.warn(`[bot-form] ${url} failed:`, e);
      return null;
    } finally {
      clearTimeout(timeout);
    }
  };

  // Client-side Binance fallback — public endpoint, no API key needed
  const fetchSymbolsDirect = async (): Promise<string[]> => {
    try {
      const res = await fetch("https://api.binance.com/api/v3/exchangeInfo");
      if (!res.ok) return [];
      const data = await res.json();
      return ((data.symbols ?? []) as Array<{ symbol: string; status: string; isSpotTradingAllowed: boolean; quoteAsset: string }>)
        .filter((s) => s.status === "TRADING" && s.isSpotTradingAllowed !== false && s.quoteAsset === "USDT")
        .map((s) => s.symbol)
        .sort();
    } catch {
      return [];
    }
  };

  // Initial data load — each fetch is independent so one failure doesn't block others
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setDataLoaded(false);
      setError(null);

      const [promptsData, modelsData, symbolsData, botData] = await Promise.all([
        safeFetch<Prompt[]>("/api/prompts"),
        safeFetch<Model[]>("/api/models"),
        safeFetch<SymbolResponse>("/api/venues/binance/symbols"),
        mode === "edit" && botId ? safeFetch<BotSetup>(`/api/bots/${botId}`) : Promise.resolve(null)
      ]);

      if (cancelled) return;

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
      if (!modelsData || modelsData.length === 0) errors.push("models");
      if (resolvedSymbols.length === 0) errors.push("symbols");
      if (mode === "edit" && botId && !botData) errors.push("bot config");
      if (errors.length) {
        setError(`Could not load: ${errors.join(", ")}. Check API connectivity or retry.`);
      }

      if (mode === "edit" && botData) {
        const setup = botData;
        const botModel = (modelsData ?? []).find((m) => m.id === setup.modelProfileId);
        if (botModel?.provider) setSelectedProvider(botModel.provider);

        setFormData({
          name: setup.name,
          promptStrategy: "existing",
          existingPromptVersionId: setup.promptVersionId,
          newPromptName: `${setup.name} Prompt`,
          newPromptBody: DEFAULT_PROMPT_BODY,
          modelProfileId: setup.modelProfileId,
          promptConfig: setup.promptConfig,
          venue: setup.runtimeConfig.venue,
          frequencyMinutes: String(setup.runtimeConfig.frequencyMinutes),
          mode: setup.runtimeConfig.mode,
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

  // Auto-select first prompt version
  useEffect(() => {
    if (!formData.existingPromptVersionId && promptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingPromptVersionId: promptOptions[0]!.id }));
    }
  }, [promptOptions, formData.existingPromptVersionId]);

  // Load prompt body when a saved version is selected
  useEffect(() => {
    if (formData.promptStrategy !== "existing" || !formData.existingPromptVersionId) {
      setPromptBody(null);
      setShowBodyEditor(false);
      return;
    }

    const prompt = prompts.find((p) => p.versions.some((v) => v.id === formData.existingPromptVersionId));
    if (!prompt) return;

    let cancelled = false;
    setLoadingBody(true);
    setShowBodyEditor(false);

    fetch(`/api/prompts/${prompt.id}/versions/${formData.existingPromptVersionId}`)
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) {
          setPromptBody(data.body ?? null);
          setEditedBody(data.body ?? "");
        }
      })
      .catch(() => { if (!cancelled) setPromptBody(null); })
      .finally(() => { if (!cancelled) setLoadingBody(false); });

    return () => { cancelled = true; };
  }, [formData.existingPromptVersionId, formData.promptStrategy, prompts]);

  const handleSaveNewVersion = async () => {
    const prompt = prompts.find((p) => p.versions.some((v) => v.id === formData.existingPromptVersionId));
    if (!prompt) return;

    setSavingVersion(true);
    setError(null);
    try {
      const res = await fetch(`/api/prompts/${prompt.id}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: editedBody })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to save version");

      const promptsRes = await fetch("/api/prompts");
      const promptsData = await promptsRes.json();
      setPrompts(promptsData);
      setFormData((cur) => ({ ...cur, existingPromptVersionId: data.promptVersionId }));
      setShowBodyEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save new version");
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
      if (!formData.existingPromptVersionId) throw new Error("Choose a saved prompt version");
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
      if (!formData.name.trim()) throw new Error("Bot name is required");
      if (!formData.modelProfileId) throw new Error("Choose a model");
      if (formData.promptStrategy === "new" && !formData.newPromptName.trim()) throw new Error("Prompt name is required");
      if (formData.promptStrategy === "new" && !formData.newPromptBody.trim()) throw new Error("Prompt body is required");
      if (formData.symbolScope === "selected" && formData.contextSymbols.length === 0) {
        throw new Error("Select at least one pair, or choose All Pairs");
      }

      const promptVersionId = await resolvePromptVersionId();
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
            modelProfileId: formData.modelProfileId,
            promptConfig: formData.promptConfig,
            runtimeConfig: {
              venue: formData.venue,
              frequencyMinutes: Number(formData.frequencyMinutes),
              mode: formData.mode,
              assetClass: "spot",
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

  const PRESETS = ["minimal", "performance", "competitive", "full-context"] as const;

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
                  Name
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="Bot #1"
                    required
                  />
                </label>
              </div>
            </div>

            {/* ── Prompt ── */}
            <div className="form-section">
              <h3>Prompt</h3>

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
                      Version
                      <select
                        value={formData.existingPromptVersionId}
                        onChange={(e) => setFormData({ ...formData, existingPromptVersionId: e.target.value })}
                        required
                      >
                        <option value="">Select a version</option>
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
                              {savingVersion ? "Saving…" : "Save as new version"}
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
                    <select value={formData.venue} disabled>
                      <option value="binance">Binance France</option>
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
                      <option value="1">Every 1 min</option>
                      <option value="5">Every 5 min</option>
                      <option value="15">Every 15 min</option>
                      <option value="30">Every 30 min</option>
                      <option value="60">Every 60 min</option>
                    </select>
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Mode
                    <select
                      value={formData.mode}
                      onChange={(e) => setFormData({ ...formData, mode: e.target.value as "testnet" | "live" })}
                      disabled={mode !== "create"}
                    >
                      <option value="testnet">Testnet</option>
                      <option value="live">Live</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>

            {/* ── Context & Behavior (preset + modules) ── */}
            <div className="form-section">
              <h3>Context &amp; Behavior</h3>
              <p className="field-help">
                Choose a preset and tick the data modules injected into every run.
              </p>

              <div className="preset-grid">
                {PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    className={`preset-option ${formData.promptConfig.preset === preset ? "preset-option-active" : ""}`}
                    onClick={() =>
                      setFormData((cur) => ({
                        ...cur,
                        promptConfig: { ...cur.promptConfig, preset }
                      }))
                    }
                  >
                    <span className="preset-label">{preset.replace("-", " ")}</span>
                    <span className="preset-desc">{PRE_PROMPT_PRESET_DESCRIPTIONS[preset]}</span>
                  </button>
                ))}
              </div>

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

            {error && <p className="form-error">{error}</p>}

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
