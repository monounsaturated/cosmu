"use client";

import { useEffect, useMemo, useState } from "react";
import { DatabaseZap, KeyRound, Plus, RefreshCw, Save, Settings2, SlidersHorizontal } from "lucide-react";
import type { ResearchDataSource } from "@cosmu/shared";

type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

type PromptProfile = {
  id: string;
  name: string;
  latestVersionId: string | null;
  latestBody: string | null;
  promptNumber: number;
};

type AppSettings = {
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
        allowMarketOrders: boolean;
        allowLimitOrders: boolean;
        maxOrdersPerRun: number;
        maxNotionalPerOrderUsd: number;
        minCashReserveUsd: number;
      };
    };
  };
  featureToggles: {
    promptLab: boolean;
    sentiment: boolean;
    signals: boolean;
    researchLab: boolean;
    proReview: boolean;
    promptLibrary: boolean;
  };
};

type Diagnostics = {
  webEnv?: { apiBaseUrl?: string; hasKey?: boolean };
  backend?: {
    modelProviderKeys?: Record<string, boolean>;
    tradingAccountKeys?: Record<string, boolean>;
  };
  backendError?: string;
};

const PROVIDERS = ["xai", "openai", "anthropic", "google", "mistral", "huggingface", "nous"] as const;

const PROVIDER_LABELS: Record<string, string> = {
  xai: "xAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  huggingface: "Hugging Face",
  google: "Google",
  mistral: "Mistral",
  nous: "Nous"
};

const DEFAULT_APP_SETTINGS: AppSettings = {
  agentDefaults: {
    research: { provider: "xai", modelProfileId: null, prompt: { mode: "new", versionId: null } },
    trader: { provider: "xai", modelProfileId: null, prompt: { mode: "saved", versionId: null } },
    runtime: {
      venue: "binance-testnet",
      frequencyMinutes: 30,
      budgetUsdt: 1000,
      symbolScope: "all",
      execution: {
        enabled: false,
        allowMarketOrders: true,
        allowLimitOrders: true,
        maxOrdersPerRun: 3,
        maxNotionalPerOrderUsd: 250,
        minCashReserveUsd: 25
      }
    }
  },
  featureToggles: {
    promptLab: false,
    sentiment: false,
    signals: false,
    researchLab: false,
    proReview: false,
    promptLibrary: false
  }
};

const mergeAppSettings = (data?: Partial<AppSettings> | null): AppSettings => {
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
    }
  };
};

const DATA_SOURCE_KINDS: ResearchDataSource["kind"][] = [
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

const DATA_SOURCE_PRESETS: Array<{
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

const providerLabel = (provider: string) => PROVIDER_LABELS[provider] ?? (provider || "custom");

const promptOptions = (prompts: PromptProfile[], label: "Research" | "Trader") =>
  prompts
    .filter((prompt) => Boolean(prompt.latestVersionId))
    .map((prompt) => ({
      id: prompt.latestVersionId!,
      label: `${label} Prompt #${prompt.promptNumber} - ${prompt.name}`
    }));

const PRODUCT_SWITCHES: Array<{
  key: keyof AppSettings["featureToggles"];
  label: string;
  description: string;
}> = [
  { key: "promptLab", label: "Prompt Lab", description: "Prompt history, experiments, and advisor surface." },
  { key: "sentiment", label: "Sentiment", description: "Market sentiment dashboards and topic scoring." },
  { key: "signals", label: "Signals", description: "Raw observations converted into standardized signals." },
  { key: "researchLab", label: "Research lab", description: "Paper-only experiments, data sources, and candidates." },
  { key: "proReview", label: "Live review", description: "Approval inbox for promoted live candidates." },
  { key: "promptLibrary", label: "Prompt library", description: "Version history and prompt inspection." }
];

export function SettingsConsole() {
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [prompts, setPrompts] = useState<PromptProfile[]>([]);
  const [traderPrompts, setTraderPrompts] = useState<PromptProfile[]>([]);
  const [sources, setSources] = useState<ResearchDataSource[]>([]);
  const [draftSources, setDraftSources] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_APP_SETTINGS);
  const [modelName, setModelName] = useState("");
  const [modelProvider, setModelProvider] = useState("xai");
  const [modelIdentifier, setModelIdentifier] = useState("");
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceKind, setSourceKind] = useState<ResearchDataSource["kind"]>("market");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const groupedModels = useMemo(() => {
    return models.reduce<Record<string, ModelProfile[]>>((groups, model) => {
      const key = model.provider;
      groups[key] = [...(groups[key] ?? []), model];
      return groups;
    }, {});
  }, [models]);

  const researchPromptOptions = useMemo(() => promptOptions(prompts, "Research"), [prompts]);
  const traderPromptOptions = useMemo(() => promptOptions(traderPrompts, "Trader"), [traderPrompts]);

  const modelsForProvider = (provider: string) => models.filter((model) => model.provider === provider);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const [modelRes, sourceRes, settingsRes, promptsRes, traderPromptsRes, diagnosticsRes] = await Promise.all([
        fetch("/api/models", { cache: "no-store" }),
        fetch("/api/research/data-sources", { cache: "no-store" }),
        fetch("/api/settings/app", { cache: "no-store" }),
        fetch("/api/prompts", { cache: "no-store" }),
        fetch("/api/trader-prompts", { cache: "no-store" }),
        fetch("/api/internal/diagnostics", { cache: "no-store" })
      ]);
      const modelData = modelRes.ok ? await modelRes.json() : [];
      const sourceData = sourceRes.ok ? await sourceRes.json() : [];
      const settingsData = settingsRes.ok ? await settingsRes.json() : DEFAULT_APP_SETTINGS;
      const promptData = promptsRes.ok ? await promptsRes.json() : [];
      const traderPromptData = traderPromptsRes.ok ? await traderPromptsRes.json() : [];
      const diagnosticsData = diagnosticsRes.ok ? await diagnosticsRes.json() : null;

      setModels(Array.isArray(modelData) ? modelData : []);
      setSources(Array.isArray(sourceData) ? sourceData : sourceData.dataSources ?? []);
      setSettings(mergeAppSettings(settingsData));
      setPrompts(Array.isArray(promptData) ? promptData : []);
      setTraderPrompts(Array.isArray(traderPromptData) ? traderPromptData : []);
      setDiagnostics(diagnosticsData);
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Settings load failed" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const updateSettings = (recipe: (current: AppSettings) => AppSettings) => {
    setSettings((current) => recipe(current));
  };

  const saveSettings = async () => {
    setSaving("app-settings");
    setMessage(null);
    try {
      const res = await fetch("/api/settings/app", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Settings save failed");
      setSettings(mergeAppSettings(data));
      setMessage({ tone: "success", text: "Settings saved" });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Settings save failed" });
    } finally {
      setSaving(null);
    }
  };

  const syncModels = async (provider = modelProvider) => {
    setSyncing(provider);
    setMessage(null);
    try {
      const res = await fetch(`/api/internal/catalog/sync?force=true&provider=${encodeURIComponent(provider)}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Model sync failed");
      await load();
      setMessage({ tone: "success", text: provider === "all" ? "All model catalogs synced" : `${providerLabel(provider)} catalog synced` });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Model sync failed" });
    } finally {
      setSyncing(null);
    }
  };

  const modelProviderKeys = diagnostics?.backend?.modelProviderKeys ?? {};
  const tradingAccountKeys = diagnostics?.backend?.tradingAccountKeys ?? {};
  const providerKeyRows = PROVIDERS.map((provider) => ({
    key: provider,
    label: providerLabel(provider),
    configured: Boolean(modelProviderKeys[provider])
  }));
  const accountKeyRows = [
    { key: "binanceLive", label: "Binance live", configured: Boolean(tradingAccountKeys.binanceLive) },
    { key: "binanceTestnet", label: "Binance testnet", configured: Boolean(tradingAccountKeys.binanceTestnet) }
  ];

  const createModel = async () => {
    const provider = modelProvider.trim();
    const model = modelIdentifier.trim();
    if (!provider || !model) return;
    setSaving("model");
    setMessage(null);
    try {
      const res = await fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: modelName.trim() || `${providerLabel(provider)} ${model}`,
          provider,
          model,
          settings: { temperature: 0.2 }
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Model creation failed");
      setModelName("");
      setModelIdentifier("");
      await load();
      setMessage({ tone: "success", text: "Model profile added" });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Model creation failed" });
    } finally {
      setSaving(null);
    }
  };

  const createSource = async (input?: { name: string; kind: ResearchDataSource["kind"]; config: Record<string, unknown> }) => {
    const name = input?.name ?? sourceName.trim();
    const kind = input?.kind ?? sourceKind;
    if (!name) return;
    setSaving("source-create");
    setMessage(null);
    try {
      const res = await fetch("/api/research/data-sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, kind, enabled: false, config: input?.config ?? { status: "planned" } })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Source creation failed");
      setSourceName("");
      await load();
      setMessage({ tone: "success", text: "Data source added off by default" });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Source creation failed" });
    } finally {
      setSaving(null);
    }
  };

  const updateSource = async (
    source: ResearchDataSource,
    patch: Partial<Pick<ResearchDataSource, "name" | "kind" | "enabled">> & { config?: unknown }
  ) => {
    setSaving(source.id);
    setMessage(null);
    try {
      const res = await fetch(`/api/research/data-sources/${source.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Source update failed");
      if (data.dataSource) {
        setSources((current) => current.map((item) => (item.id === source.id ? data.dataSource : item)));
      }
      setMessage({ tone: "success", text: "Data source saved" });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Source update failed" });
    } finally {
      setSaving(null);
    }
  };

  const saveSourceConfig = async (source: ResearchDataSource) => {
    const draft = draftSources[source.id] ?? JSON.stringify(source.config ?? {}, null, 2);
    try {
      await updateSource(source, { config: draft.trim() ? JSON.parse(draft) : {} });
    } catch {
      setMessage({ tone: "error", text: "Source config must be valid JSON" });
    }
  };

  const phaseDefaults = (phase: "research" | "trader") => {
    const phaseSettings = settings.agentDefaults[phase];
    const options = phase === "research" ? researchPromptOptions : traderPromptOptions;
    return (
      <div className="settings-group settings-default-card">
        <div className="section-header">
          <div>
            <span className="label">{phase}</span>
            <h3>{phase === "research" ? "Research defaults" : "Trader defaults"}</h3>
          </div>
        </div>

        <div className="form-grid-two">
          <label className="field">
            <span>Provider</span>
            <select
              value={phaseSettings.provider}
              onChange={(event) => {
                const provider = event.target.value as AppSettings["agentDefaults"][typeof phase]["provider"];
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    [phase]: { ...current.agentDefaults[phase], provider, modelProfileId: null }
                  }
                }));
              }}
            >
              {PROVIDERS.map((provider) => <option key={provider} value={provider}>{providerLabel(provider)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Model</span>
            <select
              value={phaseSettings.modelProfileId ?? ""}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    [phase]: {
                      ...current.agentDefaults[phase],
                      modelProfileId: event.target.value || null
                    }
                  }
                }))
              }
            >
              <option value="">Auto-pick best available</option>
              {modelsForProvider(phaseSettings.provider).map((model) => (
                <option key={model.id} value={model.id}>{model.name} ({model.model})</option>
              ))}
            </select>
          </label>
        </div>

        <div className="form-grid-two">
          <label className="field">
            <span>Default prompt</span>
            <select
              value={phaseSettings.prompt.mode}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    [phase]: {
                      ...current.agentDefaults[phase],
                      prompt: {
                        mode: event.target.value as "new" | "saved",
                        versionId: event.target.value === "saved" ? current.agentDefaults[phase].prompt.versionId : null
                      }
                    }
                  }
                }))
              }
            >
              <option value="new">New from template</option>
              <option value="saved">Saved prompt</option>
            </select>
          </label>
          <label className="field">
            <span>Saved prompt</span>
            <select
              value={phaseSettings.prompt.versionId ?? ""}
              disabled={phaseSettings.prompt.mode !== "saved"}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    [phase]: {
                      ...current.agentDefaults[phase],
                      prompt: { ...current.agentDefaults[phase].prompt, versionId: event.target.value || null }
                    }
                  }
                }))
              }
            >
              <option value="">Most recent saved prompt</option>
              {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
        </div>
      </div>
    );
  };

  return (
    <div className="settings-console">
      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Agent creation defaults</h3>
            <p className="muted">These values prefill the creation sheet for research and trader phases.</p>
          </div>
          <button className="btn btn-primary" type="button" onClick={saveSettings} disabled={saving === "app-settings"}>
            <Save size={15} />
            {saving === "app-settings" ? "Saving" : "Save settings"}
          </button>
        </div>

        <div className="settings-phase-grid">
          {phaseDefaults("research")}
          {phaseDefaults("trader")}
        </div>

        <div className="settings-runtime-grid">
          <label className="field">
            <span>Venue</span>
            <select
              value={settings.agentDefaults.runtime.venue}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    runtime: {
                      ...current.agentDefaults.runtime,
                      venue: event.target.value as AppSettings["agentDefaults"]["runtime"]["venue"]
                    }
                  }
                }))
              }
            >
              <option value="binance-testnet">Binance Testnet</option>
              <option value="binance">Binance</option>
            </select>
          </label>
          <label className="field">
            <span>Budget</span>
            <input
              type="number"
              min={10}
              step={10}
              value={settings.agentDefaults.runtime.budgetUsdt}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    runtime: { ...current.agentDefaults.runtime, budgetUsdt: Math.max(10, Number(event.target.value) || 10) }
                  }
                }))
              }
            />
          </label>
          <label className="field">
            <span>Frequency</span>
            <select
              value={settings.agentDefaults.runtime.frequencyMinutes}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    runtime: { ...current.agentDefaults.runtime, frequencyMinutes: Number(event.target.value) }
                  }
                }))
              }
            >
              {[1, 5, 15, 30, 60, 240, 720, 1440].map((minutes) => (
                <option key={minutes} value={minutes}>{minutes < 60 ? `${minutes} min` : `${minutes / 60}h`}</option>
              ))}
            </select>
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={settings.agentDefaults.runtime.execution.enabled}
              onChange={(event) =>
                updateSettings((current) => ({
                  ...current,
                  agentDefaults: {
                    ...current.agentDefaults,
                    runtime: {
                      ...current.agentDefaults.runtime,
                      execution: { ...current.agentDefaults.runtime.execution, enabled: event.target.checked }
                    }
                  }
                }))
              }
            />
            <span>Execution rules on by default</span>
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Product switches</h3>
            <p className="muted">Keep the daily workspace lean. Turn on labs only when they are actively useful.</p>
          </div>
          <span className="badge badge-neutral">opt-in</span>
        </div>
        <div className="settings-toggle-grid">
          {PRODUCT_SWITCHES.map((item) => (
            <label className="checkbox-label settings-toggle-card" key={item.key}>
              <input
                type="checkbox"
                checked={settings.featureToggles[item.key]}
                onChange={(event) =>
                  updateSettings((current) => ({
                    ...current,
                    featureToggles: { ...current.featureToggles, [item.key]: event.target.checked }
                  }))
                }
              />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Secrets and keys</h3>
            <p className="muted">Secrets stay in environment variables. The database stores only model profiles, defaults, prompt versions, and switches.</p>
          </div>
          <span className="badge badge-success">env based</span>
        </div>
        <div className="secret-policy-grid">
          <div className="secret-policy-card">
            <KeyRound size={18} />
            <span>
              <strong>Provider keys</strong>
              <small>
                <code>XAI_API_KEY</code>, <code>OPENAI_API_KEY</code>, <code>ANTHROPIC_API_KEY</code>, <code>BINANCE_*</code>, and TradingAgents keys live in <code>.env.local</code> locally and server env in deploys. Keep <code>SCHEDULER_ENABLED</code> and <code>GUARDIAN_ENABLED</code> off unless automation is intentional.
              </small>
            </span>
          </div>
          <div className="secret-policy-card">
            <SlidersHorizontal size={18} />
            <span>
              <strong>Product config</strong>
              <small>Model names, defaults, toggles, prompt versions, and data source metadata can stay in Postgres because they are not secrets.</small>
            </span>
          </div>
        </div>
        <div className="env-readiness-grid">
          <div className="settings-group">
            <span className="label">LLM access</span>
            {providerKeyRows.map((row) => (
              <div className="settings-row" key={row.key}>
                <span>
                  <strong>{row.label}</strong>
                  <small>{row.configured ? "key detected on backend" : "add key in deployment env"}</small>
                </span>
                <span className={`badge ${row.configured ? "badge-success" : "badge-inactive"}`}>{row.configured ? "ready" : "missing"}</span>
              </div>
            ))}
          </div>
          <div className="settings-group">
            <span className="label">Trading accounts</span>
            {accountKeyRows.map((row) => (
              <div className="settings-row" key={row.key}>
                <span>
                  <strong>{row.label}</strong>
                  <small>{row.configured ? "API key and secret detected" : "add key pair in deployment env"}</small>
                </span>
                <span className={`badge ${row.configured ? "badge-success" : "badge-inactive"}`}>{row.configured ? "ready" : "missing"}</span>
              </div>
            ))}
            {diagnostics?.backendError ? <p className="feedback feedback-error">{diagnostics.backendError}</p> : null}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Model catalog</h3>
            <p className="muted">Catalogs refresh from provider APIs, then fall back to known large models when a provider key is missing.</p>
          </div>
          <div className="settings-action-row">
            <button className="btn btn-secondary" type="button" onClick={() => void syncModels(modelProvider)} disabled={Boolean(syncing)}>
              <RefreshCw size={15} />
              {syncing === modelProvider ? "Syncing" : `Sync ${providerLabel(modelProvider)}`}
            </button>
            <button className="btn btn-primary" type="button" onClick={() => void syncModels("all")} disabled={Boolean(syncing)}>
              <RefreshCw size={15} />
              {syncing === "all" ? "Syncing" : "Sync all labs"}
            </button>
          </div>
        </div>

        <div className="settings-model-grid">
          {Object.entries(groupedModels).map(([provider, items]) => (
            <div key={provider} className="settings-group">
              <span className="label">{providerLabel(provider)}</span>
              {items.map((model) => (
                <div className="settings-row" key={model.id}>
                  <span>
                    <strong>{model.name}</strong>
                    <small>{model.model}</small>
                  </span>
                  <span className="badge badge-neutral">{model.provider}</span>
                </div>
              ))}
            </div>
          ))}
          {!loading && models.length === 0 && <p className="muted">No models configured yet. Sync or add a profile.</p>}
        </div>

        <div className="settings-create-row">
          <label className="field">
            <span>Name</span>
            <input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="OpenAI GPT-4.1 mini" />
          </label>
          <label className="field">
            <span>Provider</span>
            <select value={modelProvider} onChange={(event) => setModelProvider(event.target.value)}>
              {PROVIDERS.map((provider) => <option key={provider} value={provider}>{providerLabel(provider)}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Model ID</span>
            <input value={modelIdentifier} onChange={(event) => setModelIdentifier(event.target.value)} placeholder="gpt-4.1-mini" />
          </label>
          <button className="btn btn-primary" type="button" onClick={createModel} disabled={saving === "model" || !modelProvider.trim() || !modelIdentifier.trim()}>
            <Settings2 size={15} />
            Add model
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Research data sources</h3>
            <p className="muted">Sources are toggleable and intentionally off until their adapter is ready.</p>
          </div>
          <span className="badge badge-neutral">{sources.length} sources</span>
        </div>

        <div className="settings-preset-row">
          {DATA_SOURCE_PRESETS.map((preset) => (
            <button key={preset.name} className="btn btn-secondary" type="button" onClick={() => void createSource(preset)} disabled={saving === "source-create"}>
              <Plus size={14} />
              {preset.name}
            </button>
          ))}
        </div>

        <div className="settings-create-row settings-create-row-compact">
          <label className="field">
            <span>Custom source</span>
            <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="My market API" />
          </label>
          <label className="field">
            <span>Kind</span>
            <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as ResearchDataSource["kind"])}>
              {DATA_SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
            </select>
          </label>
          <button className="btn btn-primary" type="button" onClick={() => void createSource()} disabled={saving === "source-create" || !sourceName.trim()}>
            <Plus size={15} />
            Add off
          </button>
        </div>

        <div className="settings-source-list">
          {sources.map((source) => (
            <details key={source.id} className="settings-source">
              <summary>
                <span>
                  <strong>{source.name}</strong>
                  <small>{source.kind} - health {source.healthStatus}</small>
                </span>
                <span className={`badge ${source.enabled ? "badge-success" : "badge-inactive"}`}>{source.enabled ? "enabled" : "off"}</span>
              </summary>
              <div className="form-grid-two">
                <label className="field">
                  <span>Name</span>
                  <input
                    defaultValue={source.name}
                    onBlur={(event) => {
                      const name = event.target.value.trim();
                      if (name && name !== source.name) void updateSource(source, { name });
                    }}
                  />
                </label>
                <label className="field">
                  <span>Kind</span>
                  <select value={source.kind} onChange={(event) => void updateSource(source, { kind: event.target.value as ResearchDataSource["kind"] })}>
                    {DATA_SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
                  </select>
                </label>
              </div>
              <label className="checkbox-label">
                <input type="checkbox" checked={source.enabled} onChange={(event) => void updateSource(source, { enabled: event.target.checked })} />
                <span>Enabled</span>
              </label>
              <textarea
                value={draftSources[source.id] ?? JSON.stringify(source.config ?? {}, null, 2)}
                onChange={(event) => setDraftSources((current) => ({ ...current, [source.id]: event.target.value }))}
                rows={5}
              />
              <button type="button" className="btn btn-primary" onClick={() => void saveSourceConfig(source)} disabled={saving === source.id}>
                <Save size={15} />
                {saving === source.id ? "Saving" : "Save source"}
              </button>
            </details>
          ))}
          {!loading && sources.length === 0 && (
            <p className="muted"><DatabaseZap size={16} /> No data sources configured yet.</p>
          )}
        </div>
      </section>

      {message && <p className={`feedback ${message.tone === "error" ? "feedback-error" : "feedback-success"}`}>{message.text}</p>}
    </div>
  );
}
