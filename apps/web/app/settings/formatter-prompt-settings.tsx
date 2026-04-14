"use client";

import { useCallback, useEffect, useState } from "react";

type FormatterPrompts = {
  binance: string;
  "binance-testnet": string;
};

const empty: FormatterPrompts = { binance: "", "binance-testnet": "" };

export function FormatterPromptSettings() {
  const [prompts, setPrompts] = useState<FormatterPrompts>(empty);
  const [draft, setDraft] = useState<FormatterPrompts>(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/formatter-prompt");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to load");
      const p = data.formatterPrompts as FormatterPrompts;
      const next = {
        binance: typeof p?.binance === "string" ? p.binance : "",
        "binance-testnet": typeof p?.["binance-testnet"] === "string" ? p["binance-testnet"] : ""
      };
      setPrompts(next);
      setDraft(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSavedAt(null);
    try {
      const res = await fetch("/api/settings/formatter-prompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ formatterPrompts: draft })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Save failed");
      const p = data.formatterPrompts as FormatterPrompts;
      const next = {
        binance: typeof p?.binance === "string" ? p.binance : "",
        "binance-testnet": typeof p?.["binance-testnet"] === "string" ? p["binance-testnet"] : ""
      };
      setPrompts(next);
      setDraft(next);
      setSavedAt(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const dirty =
    draft.binance !== prompts.binance || draft["binance-testnet"] !== prompts["binance-testnet"];

  const hasCustomPrompt = prompts.binance.length > 0 || prompts["binance-testnet"].length > 0;

  return (
    <div className="stack" style={{ gap: "1.25rem" }}>
      <p className="muted">
        Phase 2 (execution): reads the free-form research from phase 1, uses live prices for candidate
        symbols, and must output only valid <strong>TradingDecision</strong> JSON. Hard constraints are
        appended in code. This prompt rarely needs editing.
      </p>

      {!expanded ? (
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button type="button" className="btn" onClick={() => setExpanded(true)}>
            Edit
          </button>
          <span className="muted" style={{ fontSize: "0.85rem" }}>
            {loading
              ? "Loading…"
              : hasCustomPrompt
                ? "Custom formatter prompt configured."
                : "Using built-in defaults."}
          </span>
        </div>
      ) : (
        <>
          {loading ? (
            <p className="muted">Loading…</p>
          ) : (
            <>
              <div className="panel">
                <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>Formatter — Binance (live)</h2>
                <textarea
                  className="prompt-body-textarea"
                  style={{ width: "100%", minHeight: "140px" }}
                  value={draft.binance}
                  onChange={(e) => setDraft((d) => ({ ...d, binance: e.target.value }))}
                  placeholder="Optional. Empty = built-in formatter system prompt."
                />
              </div>

              <div className="panel">
                <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>Formatter — Binance Testnet</h2>
                <textarea
                  className="prompt-body-textarea"
                  style={{ width: "100%", minHeight: "140px" }}
                  value={draft["binance-testnet"]}
                  onChange={(e) => setDraft((d) => ({ ...d, "binance-testnet": e.target.value }))}
                  placeholder="Optional. Empty = built-in formatter system prompt."
                />
              </div>

              {error && (
                <div className="form-error">
                  <p>{error}</p>
                </div>
              )}

              {savedAt && !error && (
                <p className="muted" style={{ margin: 0 }}>
                  Saved.
                </p>
              )}

              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving || !dirty}>
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setDraft(prompts);
                    setError(null);
                    setSavedAt(null);
                  }}
                  disabled={saving || !dirty}
                >
                  Revert
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setDraft(prompts);
                    setError(null);
                    setSavedAt(null);
                    setExpanded(false);
                  }}
                  disabled={dirty}
                >
                  Collapse
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
