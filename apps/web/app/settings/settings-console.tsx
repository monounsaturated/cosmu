"use client";

import { useEffect, useMemo, useState } from "react";
import { DatabaseZap, RefreshCw, Save, Settings2 } from "lucide-react";
import type { ResearchDataSource } from "@cosmu/shared";

type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
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

const providerLabel = (provider: string) => provider || "custom";

export function SettingsConsole() {
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [sources, setSources] = useState<ResearchDataSource[]>([]);
  const [draftSources, setDraftSources] = useState<Record<string, string>>({});
  const [modelName, setModelName] = useState("");
  const [modelProvider, setModelProvider] = useState("xai");
  const [modelIdentifier, setModelIdentifier] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const groupedModels = useMemo(() => {
    return models.reduce<Record<string, ModelProfile[]>>((groups, model) => {
      const key = providerLabel(model.provider);
      groups[key] = [...(groups[key] ?? []), model];
      return groups;
    }, {});
  }, [models]);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const [modelRes, sourceRes] = await Promise.all([
        fetch("/api/models", { cache: "no-store" }),
        fetch("/api/research/data-sources", { cache: "no-store" })
      ]);
      const modelData = modelRes.ok ? await modelRes.json() : [];
      const sourceData = sourceRes.ok ? await sourceRes.json() : [];
      setModels(Array.isArray(modelData) ? modelData : []);
      setSources(Array.isArray(sourceData) ? sourceData : sourceData.dataSources ?? []);
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Settings load failed" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const syncModels = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const res = await fetch("/api/internal/catalog/sync?force=true", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Model sync failed");
      await load();
      setMessage({ tone: "success", text: "Model catalog synced" });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : "Model sync failed" });
    } finally {
      setSyncing(false);
    }
  };

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
          name: modelName.trim() || `${provider} ${model}`,
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

  const updateSource = async (source: ResearchDataSource, patch: Partial<Pick<ResearchDataSource, "name" | "kind" | "enabled">> & { config?: unknown }) => {
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
        setSources((current) => current.map((item) => item.id === source.id ? data.dataSource : item));
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

  return (
    <div className="settings-console">
      <section className="panel">
        <div className="section-header">
          <div>
            <h3>Model catalog</h3>
            <p className="muted">These profiles are available to Research and Trader phases.</p>
          </div>
          <button className="btn btn-secondary" type="button" onClick={syncModels} disabled={syncing}>
            <RefreshCw size={15} />
            {syncing ? "Syncing" : "Sync"}
          </button>
        </div>

        <div className="settings-model-grid">
          {Object.entries(groupedModels).map(([provider, items]) => (
            <div key={provider} className="settings-group">
              <span className="label">{provider}</span>
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
          {!loading && models.length === 0 && <p className="muted">No models configured yet. Sync or add a model profile.</p>}
        </div>

        <div className="settings-create-row">
          <label className="field">
            <span>Name</span>
            <input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="xAI grok-3" />
          </label>
          <label className="field">
            <span>Provider</span>
            <input value={modelProvider} onChange={(event) => setModelProvider(event.target.value)} placeholder="xai" />
          </label>
          <label className="field">
            <span>Model ID</span>
            <input value={modelIdentifier} onChange={(event) => setModelIdentifier(event.target.value)} placeholder="grok-3" />
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
            <p className="muted">Toggle and configure what the research agent may read.</p>
          </div>
          <span className="badge badge-neutral">{sources.length} sources</span>
        </div>

        <div className="settings-source-list">
          {sources.map((source) => (
            <details key={source.id} className="settings-source">
              <summary>
                <span>
                  <strong>{source.name}</strong>
                  <small>{source.kind} · health {source.healthStatus}</small>
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
                  <select
                    value={source.kind}
                    onChange={(event) => void updateSource(source, { kind: event.target.value as ResearchDataSource["kind"] })}
                  >
                    {DATA_SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
                  </select>
                </label>
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={source.enabled}
                  onChange={(event) => void updateSource(source, { enabled: event.target.checked })}
                />
                <span>Enabled</span>
              </label>
              <textarea
                value={draftSources[source.id] ?? JSON.stringify(source.config ?? {}, null, 2)}
                onChange={(event) => setDraftSources((current) => ({ ...current, [source.id]: event.target.value }))}
                rows={5}
              />
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void saveSourceConfig(source)}
                disabled={saving === source.id}
              >
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
