"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type Preprompts = {
  binance: string;
  "binance-testnet": string;
};

const empty: Preprompts = { binance: "", "binance-testnet": "" };

export function PrepromptSettings() {
  const [preprompts, setPreprompts] = useState<Preprompts>(empty);
  const [draft, setDraft] = useState<Preprompts>(empty);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/preprompt");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to load");
      const p = data.preprompts as Preprompts;
      const next = {
        binance: typeof p?.binance === "string" ? p.binance : "",
        "binance-testnet": typeof p?.["binance-testnet"] === "string" ? p["binance-testnet"] : ""
      };
      setPreprompts(next);
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
      const res = await fetch("/api/settings/preprompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preprompts: draft })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Save failed");
      const p = data.preprompts as Preprompts;
      const next = {
        binance: typeof p?.binance === "string" ? p.binance : "",
        "binance-testnet": typeof p?.["binance-testnet"] === "string" ? p["binance-testnet"] : ""
      };
      setPreprompts(next);
      setDraft(next);
      setSavedAt(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const dirty =
    draft.binance !== preprompts.binance || draft["binance-testnet"] !== preprompts["binance-testnet"];

  return (
    <div className="stack" style={{ gap: "1.25rem" }}>
      <p className="muted">
        This text is prepended as the <strong>system</strong> message preamble for every bot run on that
        venue (before the bot&apos;s strategy prompt and hard constraints). Leave empty to use the built-in
        default. Edit here instead of baking venue-wide instructions into each bot prompt.
      </p>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="panel">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>Binance (live)</h2>
            <p className="field-help" style={{ marginBottom: "0.5rem" }}>
              Venue key: <code>binance</code>
            </p>
            <textarea
              className="prompt-body-textarea"
              style={{ width: "100%", minHeight: "120px" }}
              value={draft.binance}
              onChange={(e) => setDraft((d) => ({ ...d, binance: e.target.value }))}
              placeholder="Optional. Empty = default preamble."
            />
          </div>

          <div className="panel">
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>Binance Testnet</h2>
            <p className="field-help" style={{ marginBottom: "0.5rem" }}>
              Venue key: <code>binance-testnet</code>
            </p>
            <textarea
              className="prompt-body-textarea"
              style={{ width: "100%", minHeight: "120px" }}
              value={draft["binance-testnet"]}
              onChange={(e) => setDraft((d) => ({ ...d, "binance-testnet": e.target.value }))}
              placeholder="Optional. Empty = default preamble."
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
                setDraft(preprompts);
                setError(null);
                setSavedAt(null);
              }}
              disabled={saving || !dirty}
            >
              Revert
            </button>
            <Link href="/" className="btn" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
              Dashboard
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
