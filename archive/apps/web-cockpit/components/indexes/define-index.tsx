"use client";

// module: the "Define index" form — the operator creates a new index (social account/bucket · event topic ·
// prompt rubric). It POSTs an IndexSpec to the engine through the same-origin proxy (/api/engine/indexes); the
// engine validates the kind-specific definition (422 on a bad shape) and registers the DEFINITION only — the
// compute pass populates the series later. On success it refreshes the server-rendered list. HONEST: surfaces
// the engine's error verbatim; never fabricates a success.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { IndexDefineResponse, IndexSpec } from "@cosmu/contracts-ts";
import { engineFetch } from "@/lib/engine";

type Kind = IndexSpec["kind"];

const KIND_OPTIONS: { value: Kind; label: string; hint: string }[] = [
  { value: "event_topic", label: "Event topic", hint: "News on a topic (e.g. Middle East conflict) → sentiment, scored each pass." },
  { value: "prompt_rubric", label: "Prompt rubric", hint: "A rubric you write; an LLM judge scores it to a number against fixed anchors." },
  { value: "single_account", label: "Single account", hint: "One social handle's credibility-weighted directional signal." },
  { value: "social_bucket", label: "Social bucket", hint: "Several handles, fused by historical skill (Brier) — not follower count." },
];

function splitList(v: string): string[] {
  return v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}

export function DefineIndexForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [rationale, setRationale] = useState("");
  const [kind, setKind] = useState<Kind>("event_topic");
  const [topic, setTopic] = useState("");
  const [prompt, setPrompt] = useState("");
  const [handles, setHandles] = useState("");
  const [entities, setEntities] = useState("");
  const [status, setStatus] = useState<"draft" | "active">("active");

  function buildDefinition(): Record<string, unknown> {
    if (kind === "event_topic") return { topic };
    if (kind === "prompt_rubric") return { prompt };
    return { handles: splitList(handles) };
  }

  function submit() {
    setError(null);
    const body: IndexSpec = {
      id: id.trim(),
      name: name.trim(),
      rationale: rationale.trim(),
      kind,
      definition: buildDefinition(),
      entities: splitList(entities),
      status,
    };
    start(async () => {
      try {
        const res = await engineFetch("/indexes", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        if (res.status === 422) {
          setError("The engine rejected this definition. Check the kind-specific fields (e.g. single account = exactly one handle).");
          return;
        }
        const data = (await res.json()) as IndexDefineResponse;
        if (!res.ok || !data.ok) {
          setError(data?.error ?? `Engine returned ${res.status}.`);
          return;
        }
        router.refresh();
        onClose();
      } catch {
        setError("Could not reach the engine. Nothing was created.");
      }
    });
  }

  const kindHint = KIND_OPTIONS.find((k) => k.value === kind)?.hint;

  return (
    <div className="card" style={{ marginBottom: "var(--gap)" }}>
      <div className="card-hdr">
        <span className="card-lbl">Define an index</span>
        <button type="button" className="seeall-btn" onClick={onClose}>Cancel</button>
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <label className="idx-field">
            <span className="idx-label">ID (slug)</span>
            <input className="search-input" value={id} onChange={(e) => setId(e.target.value)} placeholder="mideast-news" />
          </label>
          <label className="idx-field" style={{ flex: 1, minWidth: 180 }}>
            <span className="idx-label">Name</span>
            <input className="search-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Middle East news" />
          </label>
        </div>

        <label className="idx-field">
          <span className="idx-label">Rationale — what it measures &amp; why it should carry signal</span>
          <textarea className="search-input" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)}
            placeholder="Geopolitical risk proxy: escalation in the region front-runs risk-off moves in crypto." />
        </label>

        <label className="idx-field">
          <span className="idx-label">Kind</span>
          <select className="search-input" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            {KIND_OPTIONS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
          {kindHint ? <span className="quiet" style={{ fontSize: 10.5, marginTop: 3 }}>{kindHint}</span> : null}
        </label>

        {kind === "event_topic" ? (
          <label className="idx-field">
            <span className="idx-label">Topic / GDELT query</span>
            <input className="search-input" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="middle east conflict" />
          </label>
        ) : null}
        {kind === "prompt_rubric" ? (
          <label className="idx-field">
            <span className="idx-label">Scoring prompt (the question the LLM judges, against fixed anchors)</span>
            <textarea className="search-input" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
              placeholder="The macro risk appetite of markets implied by the evidence, -1 (risk-off) to +1 (risk-on)." />
          </label>
        ) : null}
        {kind === "single_account" || kind === "social_bucket" ? (
          <label className="idx-field">
            <span className="idx-label">{kind === "single_account" ? "Handle (one)" : "Handles (one per line / comma-separated)"}</span>
            <textarea className="search-input" rows={kind === "single_account" ? 1 : 3} value={handles}
              onChange={(e) => setHandles(e.target.value)} placeholder={kind === "single_account" ? "@balajis" : "@balajis\n@RaoulGMI\nr/CryptoMarkets"} />
          </label>
        ) : null}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <label className="idx-field" style={{ flex: 1, minWidth: 180 }}>
            <span className="idx-label">Entities (optional — blank = one market-wide series)</span>
            <input className="search-input" value={entities} onChange={(e) => setEntities(e.target.value)} placeholder="BTC, ETH" />
          </label>
          <label className="idx-field">
            <span className="idx-label">Status</span>
            <select className="search-input" value={status} onChange={(e) => setStatus(e.target.value as "draft" | "active")}>
              <option value="active">Active (computed each pass)</option>
              <option value="draft">Draft (not computed)</option>
            </select>
          </label>
        </div>

        {error ? <p className="dn" style={{ fontSize: 11.5 }}>{error}</p> : null}

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button type="button" className="btn-col-picker" onClick={submit} disabled={pending || !id.trim() || !name.trim() || !rationale.trim()}>
            {pending ? "Creating…" : "Create index"}
          </button>
          <span className="quiet" style={{ fontSize: 10.5 }}>Registers the definition. The compute pass populates the series (heavy: cron / Modal).</span>
        </div>
      </div>
    </div>
  );
}
