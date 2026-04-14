"use client";

import { useEffect, useMemo, useState } from "react";
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
  Array.from(new Set(symbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean)));

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
    symbolScope: "selected" as "selected" | "all",
    contextSymbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
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
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [symbolSearch, setSymbolSearch] = useState("");
  const [symbolsExpanded, setSymbolsExpanded] = useState(false);
  const [formData, setFormData] = useState(buildDefaultState(defaultBotNumber));

  const availableModels = useMemo(
    () =>
      models.filter((model) => {
        const normalizedModel = model.model.toLowerCase();
        const normalizedName = model.name.toLowerCase();
        return model.provider.toLowerCase() === "xai" && (normalizedModel.includes("grok") || normalizedName.includes("grok"));
      }),
    [models]
  );

  const promptOptions = useMemo(
    () =>
      prompts
        .flatMap((prompt) =>
          [...prompt.versions]
            .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
            .map((version) => ({
              id: version.id,
              createdAt: version.createdAt,
              label: `${prompt.name} v${version.version}`
            }))
        )
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt)),
    [prompts]
  );

  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toUpperCase();
    const source = query ? symbols.filter((symbol) => symbol.includes(query)) : symbols;
    return source.slice(0, 120);
  }, [symbolSearch, symbols]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const requests: Promise<Response>[] = [fetch("/api/prompts"), fetch("/api/models"), fetch("/api/venues/binance/symbols")];
        if (mode === "edit" && botId) {
          requests.push(fetch(`/api/bots/${botId}`));
        }

        const responses = await Promise.all(requests);
        const [promptsRes, modelsRes, symbolsRes, botRes] = responses;

        const [promptsData, modelsData, symbolsData, botData] = await Promise.all([
          promptsRes.json(),
          modelsRes.json(),
          symbolsRes.json(),
          botRes ? botRes.json() : Promise.resolve(null)
        ]);

        if (!promptsRes.ok) throw new Error(promptsData.error ?? "Failed to load prompts");
        if (!modelsRes.ok) throw new Error(modelsData.error ?? "Failed to load models");
        if (!symbolsRes.ok) throw new Error(symbolsData.error ?? "Failed to load symbols");
        if (botRes && !botRes.ok) throw new Error(botData?.error ?? "Failed to load bot");

        if (cancelled) return;

        setPrompts(promptsData);
        setModels(modelsData);
        setSymbols((symbolsData as SymbolResponse).symbols);

        if (mode === "edit" && botData) {
          const setup = botData as BotSetup;
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
        } else {
          setFormData((current) => ({
            ...current,
            modelProfileId: current.modelProfileId || modelsData[0]?.id || "",
            existingPromptVersionId: current.existingPromptVersionId || promptOptions[0]?.id || ""
          }));
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load bot form");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();
    const refreshInterval = setInterval(load, 20000);

    return () => {
      cancelled = true;
      clearInterval(refreshInterval);
    };
  }, [botId, mode, defaultBotNumber]);

  useEffect(() => {
    if (!formData.modelProfileId && availableModels[0]?.id) {
      setFormData((current) => ({ ...current, modelProfileId: availableModels[0]!.id }));
    }
  }, [availableModels, formData.modelProfileId]);

  useEffect(() => {
    if (!formData.existingPromptVersionId && promptOptions[0]?.id) {
      setFormData((current) => ({ ...current, existingPromptVersionId: promptOptions[0]!.id }));
    }
  }, [promptOptions, formData.existingPromptVersionId]);

  const toggleSymbol = (symbol: string) => {
    setFormData((current) => ({
      ...current,
      contextSymbols: current.contextSymbols.includes(symbol)
        ? current.contextSymbols.filter((value) => value !== symbol)
        : [...current.contextSymbols, symbol]
    }));
  };

  const resolvePromptVersionId = async () => {
    if (formData.promptStrategy === "existing") {
      if (!formData.existingPromptVersionId) {
        throw new Error("Choose a saved prompt version");
      }

      return formData.existingPromptVersionId;
    }

    const promptResponse = await fetch("/api/prompts", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name: formData.newPromptName.trim(),
        slug: uniqueSlug(formData.newPromptName),
        initialBody: formData.newPromptBody.trim()
      })
    });

    const promptData = await promptResponse.json();
    if (!promptResponse.ok) {
      throw new Error(promptData.error ?? "Failed to create prompt");
    }

    return promptData.promptVersionId as string;
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      if (!formData.name.trim()) {
        throw new Error("Bot name is required");
      }
      if (!formData.modelProfileId) {
        throw new Error("Choose a Grok model");
      }
      if (formData.promptStrategy === "new" && !formData.newPromptName.trim()) {
        throw new Error("Prompt name is required");
      }
      if (formData.promptStrategy === "new" && !formData.newPromptBody.trim()) {
        throw new Error("Prompt body is required");
      }
      if (formData.symbolScope === "selected" && formData.contextSymbols.length === 0) {
        throw new Error("Choose at least one symbol or switch to all symbols");
      }

      const promptVersionId = await resolvePromptVersionId();
      const contextSymbols =
        formData.symbolScope === "all" ? [ALL_SYMBOLS_TOKEN] : uniqueSymbols(formData.contextSymbols);

      const payload = {
        name: formData.name.trim(),
        promptVersionId,
        modelProfileId: formData.modelProfileId,
        promptConfig: formData.promptConfig,
        frequencyMinutes: Number(formData.frequencyMinutes),
        mode: formData.mode,
        contextSymbols,
        execution: formData.execution
      };

      if (mode === "create") {
        const response = await fetch("/api/bots", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            ...payload,
            slug: uniqueSlug(formData.name),
            runtimeConfig: {
              venue: formData.venue,
              frequencyMinutes: payload.frequencyMinutes,
              mode: payload.mode,
              assetClass: "spot",
              symbolScope: formData.symbolScope,
              execution: payload.execution,
              contextSymbols
            }
          })
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error ?? "Failed to create bot");
        }
      } else {
        const response = await fetch(`/api/bots/${botId}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            name: payload.name
          })
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error ?? "Failed to update bot");
        }
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
      <div className="modal-content modal-content-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{mode === "create" ? "Create Bot" : "Rename Bot"}</h2>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>

        {loading ? (
          <p className="muted">Loading configuration...</p>
        ) : (
          <form className="modal-form" onSubmit={handleSubmit}>
            <div className="form-section">
              <h3>Bot</h3>
              <div className="form-row">
                <label>
                  Bot Name
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(event) => setFormData({ ...formData, name: event.target.value })}
                    placeholder="Bot #1"
                    required
                  />
                </label>
              </div>
            </div>

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
                <>
                  <div className="form-row">
                    <label>
                      Prompt Name
                      <input
                        type="text"
                        value={formData.newPromptName}
                        onChange={(event) => setFormData({ ...formData, newPromptName: event.target.value })}
                        placeholder="Bot #1 Prompt"
                        required
                      />
                    </label>
                  </div>
                  <div className="form-row">
                    <label>
                      Prompt Body
                      <textarea
                        value={formData.newPromptBody}
                        onChange={(event) => setFormData({ ...formData, newPromptBody: event.target.value })}
                        rows={10}
                        required
                      />
                    </label>
                  </div>
                </>
              ) : (
                <div className="form-row">
                  <label>
                    Choose a saved prompt version
                    <select
                      value={formData.existingPromptVersionId}
                      onChange={(event) => setFormData({ ...formData, existingPromptVersionId: event.target.value })}
                      required
                    >
                      <option value="">Select a prompt</option>
                      {promptOptions.map((prompt) => (
                        <option key={prompt.id} value={prompt.id}>
                          {prompt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
            </div>

            <div className="form-section">
              <h3>Model + Runtime</h3>
              <div className="form-grid">
                <div className="form-row">
                  <label>
                    Grok model (auto-refreshed)
                    <select
                      value={formData.modelProfileId}
                      onChange={(event) => setFormData({ ...formData, modelProfileId: event.target.value })}
                      required
                      disabled={mode !== "create" || availableModels.length === 0}
                    >
                      <option value="">{availableModels.length === 0 ? "No Grok model available" : "Select a model"}</option>
                      {availableModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} ({model.provider}/{model.model})
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="field-help">Fetched from API every 20s while this modal is open.</p>
                </div>

                <div className="form-row">
                  <label>
                    Pre-prompt preset
                    <select
                      value={formData.promptConfig.preset}
                      onChange={(event) =>
                        setFormData({
                          ...formData,
                          promptConfig: {
                            ...formData.promptConfig,
                            preset: event.target.value as "minimal" | "performance" | "competitive" | "full-context"
                          }
                        })
                      }
                    >
                      <option value="minimal">Minimal</option>
                      <option value="performance">Performance-aware</option>
                      <option value="competitive">Competitive</option>
                      <option value="full-context">Full context</option>
                    </select>
                  </label>
                  <p className="field-help">
                    {PRE_PROMPT_PRESET_DESCRIPTIONS[formData.promptConfig.preset]}
                  </p>
                </div>

                <div className="form-row">
                  <label>
                    Venue
                    <select value={formData.venue} disabled>
                      <option value="binance">Binance France</option>
                    </select>
                  </label>
                  <p className="field-help">One venue per bot. Venue is fixed after creation.</p>
                </div>

                <div className="form-row">
                  <label>
                    Frequency
                    <select
                      value={formData.frequencyMinutes}
                      onChange={(event) => setFormData({ ...formData, frequencyMinutes: event.target.value })}
                    >
                      <option value="1">1 minute</option>
                      <option value="5">5 minutes</option>
                      <option value="15">15 minutes</option>
                      <option value="30">30 minutes</option>
                      <option value="60">60 minutes</option>
                    </select>
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Mode
                    <select
                      value={formData.mode}
                      onChange={(event) =>
                        setFormData({ ...formData, mode: event.target.value as "testnet" | "live" })
                      }
                    >
                      <option value="testnet">Testnet</option>
                      <option value="live">Live</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>

            <div className="form-section">
              <h3>Structured Context Modules</h3>
              <p className="field-help">
                Tick the modules you want the backend to fetch dynamically and inject into the LLM input in a structured
                way before each run.
              </p>

              <div className="checkbox-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.promptConfig.modules.includeCurrentPositions}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        promptConfig: {
                          ...formData.promptConfig,
                          modules: {
                            ...formData.promptConfig.modules,
                            includeCurrentPositions: event.target.checked
                          }
                        }
                      })
                    }
                  />
                  <span>Current positions and prices</span>
                </label>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.promptConfig.modules.includeWalletOverview}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        promptConfig: {
                          ...formData.promptConfig,
                          modules: {
                            ...formData.promptConfig.modules,
                            includeWalletOverview: event.target.checked
                          }
                        }
                      })
                    }
                  />
                  <span>Wallet start vs current value</span>
                </label>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.promptConfig.modules.includePerformanceStats}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        promptConfig: {
                          ...formData.promptConfig,
                          modules: {
                            ...formData.promptConfig.modules,
                            includePerformanceStats: event.target.checked
                          }
                        }
                      })
                    }
                  />
                  <span>Performance stats</span>
                </label>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.promptConfig.modules.includePastTrades}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        promptConfig: {
                          ...formData.promptConfig,
                          modules: {
                            ...formData.promptConfig.modules,
                            includePastTrades: event.target.checked
                          }
                        }
                      })
                    }
                  />
                  <span>Past trades</span>
                </label>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.promptConfig.modules.includeBotRanking}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        promptConfig: {
                          ...formData.promptConfig,
                          modules: {
                            ...formData.promptConfig.modules,
                            includeBotRanking: event.target.checked
                          }
                        }
                      })
                    }
                  />
                  <span>Ranking vs other bots</span>
                </label>
              </div>

              {formData.promptConfig.modules.includePastTrades && (
                <div className="form-row">
                  <label>
                    Past trades lookback
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={formData.promptConfig.modules.pastTradesLookback}
                      onChange={(event) =>
                        setFormData({
                          ...formData,
                          promptConfig: {
                            ...formData.promptConfig,
                            modules: {
                              ...formData.promptConfig.modules,
                              pastTradesLookback: Number(event.target.value)
                            }
                          }
                        })
                      }
                    />
                  </label>
                </div>
              )}
            </div>

            <div className="form-section">
              <h3>Symbol Universe</h3>
              <div className="segmented-control">
                <button
                  type="button"
                  className={`segmented-option ${formData.symbolScope === "all" ? "segmented-option-active" : ""}`}
                  onClick={() =>
                    setFormData({
                      ...formData,
                      symbolScope: "all",
                      contextSymbols: []
                    })
                  }
                >
                  All Binance France spot symbols
                </button>
                <button
                  type="button"
                  className={`segmented-option ${formData.symbolScope === "selected" ? "segmented-option-active" : ""}`}
                  onClick={() => setFormData({ ...formData, symbolScope: "selected" })}
                >
                  Pick a few symbols
                </button>
              </div>

              <div className="form-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.symbolScope === "all"}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        symbolScope: event.target.checked ? "all" : "selected",
                        contextSymbols: event.target.checked ? [] : formData.contextSymbols
                      })
                    }
                  />
                  <span>All Pairs</span>
                </label>
              </div>

              <button
                type="button"
                className="btn"
                onClick={() => setSymbolsExpanded((current) => !current)}
                disabled={formData.symbolScope === "all"}
              >
                {symbolsExpanded ? "Hide authorized pairs" : "Authorized pairs"}
              </button>

              {formData.symbolScope === "selected" && symbolsExpanded ? (
                <>
                  <div className="form-row">
                    <label>
                      Search symbols
                      <input
                        type="text"
                        value={symbolSearch}
                        onChange={(event) => setSymbolSearch(event.target.value)}
                        placeholder="Search BTCUSDT, ETHUSDT..."
                      />
                    </label>
                  </div>

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
                    {formData.contextSymbols.length === 0 && <span className="muted">No symbols selected yet.</span>}
                  </div>

                  <div className="symbol-list">
                    {filteredSymbols.map((symbol) => (
                      <label key={symbol} className="symbol-option">
                        <input
                          type="checkbox"
                          checked={formData.contextSymbols.includes(symbol)}
                          onChange={() => toggleSymbol(symbol)}
                        />
                        <span>{symbol}</span>
                      </label>
                    ))}
                  </div>
                </>
              ) : (
                <p className="field-help">
                  {formData.symbolScope === "all"
                    ? "All spot pairs are authorized. Individual selection is disabled."
                    : "Open Authorized pairs to search and tick allowed pairs one by one."}
                </p>
              )}
            </div>

            <div className="form-section">
              <h3>Execution Rules</h3>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={formData.execution.enabled}
                  onChange={(event) =>
                    setFormData({
                      ...formData,
                      execution: {
                        ...formData.execution,
                        enabled: event.target.checked
                      }
                    })
                  }
                />
                <span>Enable execution rules</span>
              </label>
              <p className="field-help">Disabled by default. When off, only venue tradability and wallet sanity checks apply.</p>
              <div className="checkbox-row">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.execution.allowMarketOrders}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        execution: { ...formData.execution, allowMarketOrders: event.target.checked }
                      })
                    }
                    disabled={!formData.execution.enabled}
                  />
                  <span>Allow market orders</span>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={formData.execution.allowLimitOrders}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        execution: { ...formData.execution, allowLimitOrders: event.target.checked }
                      })
                    }
                    disabled={!formData.execution.enabled}
                  />
                  <span>Allow limit orders</span>
                </label>
              </div>

              <div className="form-grid">
                <div className="form-row">
                  <label>
                    Max orders per run
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={formData.execution.maxOrdersPerRun}
                      onChange={(event) =>
                        setFormData({
                          ...formData,
                          execution: { ...formData.execution, maxOrdersPerRun: Number(event.target.value) }
                        })
                      }
                      disabled={!formData.execution.enabled}
                    />
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Max notional per order (USD)
                    <input
                      type="number"
                      min={1}
                      value={formData.execution.maxNotionalPerOrderUsd}
                      onChange={(event) =>
                        setFormData({
                          ...formData,
                          execution: {
                            ...formData.execution,
                            maxNotionalPerOrderUsd: Number(event.target.value)
                          }
                        })
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
                      onChange={(event) =>
                        setFormData({
                          ...formData,
                          execution: {
                            ...formData.execution,
                            minCashReserveUsd: Number(event.target.value)
                          }
                        })
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
                {saving ? (mode === "create" ? "Creating..." : "Saving...") : mode === "create" ? "Create Bot" : "Save Changes"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
