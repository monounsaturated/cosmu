"use client";

import { useState, useEffect } from "react";

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

type CreateBotModalProps = {
  onClose: () => void;
  onSuccess: () => void;
};

export function CreateBotModal({ onClose, onSuccess }: CreateBotModalProps) {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    slug: "",
    promptVersionId: "",
    modelProfileId: "",
    frequencyMinutes: "15",
    mode: "testnet" as "testnet" | "live",
    contextSymbols: "BTCUSDT,ETHUSDT,SOLUSDT"
  });

  useEffect(() => {
    const loadData = async () => {
      try {
        const [promptsRes, modelsRes] = await Promise.all([
          fetch("/api/prompts"),
          fetch("/api/models")
        ]);

        if (promptsRes.ok) setPrompts(await promptsRes.json());
        if (modelsRes.ok) setModels(await modelsRes.json());
      } catch (e) {
        console.error("Failed to load prompts/models", e);
      }
    };

    loadData();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await fetch("/api/bots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formData.name,
          slug: formData.slug,
          promptVersionId: formData.promptVersionId,
          modelProfileId: formData.modelProfileId,
          runtimeConfig: {
            venue: "binance",
            frequencyMinutes: Number(formData.frequencyMinutes),
            mode: formData.mode,
            assetClass: "spot",
            execution: {
              allowMarketOrders: true,
              allowLimitOrders: true,
              maxOrdersPerRun: 3,
              maxNotionalPerOrderUsd: 250,
              minCashReserveUsd: 25
            },
            contextSymbols: formData.contextSymbols.split(",").map((s) => s.trim())
          }
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error ?? "Failed to create bot");
      }

      onSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create bot");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Create New Bot</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <form className="modal-form" onSubmit={handleSubmit}>
          <div className="form-row">
            <label>
              Bot Name
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="My Trading Bot"
                required
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Slug (unique ID)
              <input
                type="text"
                value={formData.slug}
                onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                placeholder="my-trading-bot"
                required
                pattern="[a-z0-9-]+"
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Prompt Version
              <select
                value={formData.promptVersionId}
                onChange={(e) => setFormData({ ...formData, promptVersionId: e.target.value })}
                required
              >
                <option value="">Select a prompt version</option>
                {prompts.flatMap((p) =>
                  p.versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {p.name} v{v.version}
                    </option>
                  ))
                )}
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Model Profile
              <select
                value={formData.modelProfileId}
                onChange={(e) => setFormData({ ...formData, modelProfileId: e.target.value })}
                required
              >
                <option value="">Select a model</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} ({m.provider}/{m.model})
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Frequency (minutes)
              <select
                value={formData.frequencyMinutes}
                onChange={(e) => setFormData({ ...formData, frequencyMinutes: e.target.value })}
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
                onChange={(e) => setFormData({ ...formData, mode: e.target.value as "testnet" | "live" })}
              >
                <option value="testnet">Testnet</option>
                <option value="live">Live (REAL MONEY)</option>
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Context Symbols (comma-separated)
              <input
                type="text"
                value={formData.contextSymbols}
                onChange={(e) => setFormData({ ...formData, contextSymbols: e.target.value })}
                placeholder="BTCUSDT,ETHUSDT"
              />
            </label>
          </div>

          {error && <p className="form-error">{error}</p>}

          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? "Creating..." : "Create Bot"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
