"use client";

import { useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import type { RawObservation, StandardizedSignal } from "@cosmu/shared";
import { LocalTime } from "../local-time";

type Props = {
  initialSignals: StandardizedSignal[];
  initialObservations: RawObservation[];
};

const toneForDirection = (direction: StandardizedSignal["direction"]) => {
  if (direction === "bullish") return "signal-bullish";
  if (direction === "bearish") return "signal-bearish";
  if (direction === "mixed") return "signal-mixed";
  return "signal-neutral";
};

const scoreLabel = (value: number) => {
  const signed = value > 0 ? "+" : "";
  return `${signed}${value.toFixed(2)}`;
};

export function SignalConsole({ initialSignals, initialObservations }: Props) {
  const router = useRouter();
  const [signals, setSignals] = useState(initialSignals);
  const [observations, setObservations] = useState(initialObservations);
  const [sourceKind, setSourceKind] = useState<RawObservation["sourceKind"]>("manual");
  const [sourceName, setSourceName] = useState("Manual QA");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [asset, setAsset] = useState("BTC");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [direction, setDirection] = useState<StandardizedSignal["direction"]>("neutral");
  const [confidence, setConfidence] = useState(0.65);
  const [urgency, setUrgency] = useState<StandardizedSignal["urgency"]>("medium");
  const [summary, setSummary] = useState("");
  const [useLLMFormat, setUseLLMFormat] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [, startTransition] = useTransition();

  const stats = useMemo(() => {
    const watch = signals.filter((signal) => signal.status === "watching" || signal.status === "new").length;
    const highUrgency = signals.filter((signal) => signal.urgency === "high").length;
    const avgConfidence = signals.length === 0
      ? 0
      : signals.reduce((sum, signal) => sum + signal.confidence, 0) / signals.length;
    return { watch, highUrgency, avgConfidence };
  }, [signals]);

  const submitSignal = async (event: FormEvent) => {
    event.preventDefault();
    const cleanTitle = title.trim();
    const cleanContent = content.trim();
    const cleanSummary = summary.trim();
    const cleanAsset = asset.trim().toUpperCase();
    if (!cleanTitle || !cleanContent || (!useLLMFormat && (!cleanSummary || !cleanAsset))) return;
    setSubmitting(true);
    setError(null);
    try {
      const observationPayload = {
        sourceKind,
        sourceName: sourceName.trim() || "Manual QA",
        title: cleanTitle,
        content: cleanContent
      };
      const res = await fetch(useLLMFormat ? "/api/signals/format" : "/api/signals/observations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(useLLMFormat
          ? observationPayload
          : {
              ...observationPayload,
              signal: {
                asset: cleanAsset,
                symbol: symbol.trim().toUpperCase() || null,
                topic: cleanTitle,
                direction,
                sentimentScore: direction === "bullish" ? 0.55 : direction === "bearish" ? -0.55 : 0,
                confidence,
                urgency,
                horizon: "intraday",
                summary: cleanSummary,
                evidenceJson: [{ title: cleanTitle, source: sourceName.trim() || "Manual QA" }],
                reasoningSummary: "Manual QA signal. Replace with LLM formatter output in automated runs."
              }
            })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Signal capture failed");
      if (data.observation) setObservations((current) => [data.observation, ...current]);
      if (data.signal) setSignals((current) => [data.signal, ...current]);
      setTitle("");
      setContent("");
      setSummary("");
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signal capture failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="signals-layout">
      <section className="signal-hero">
        <div>
          <p className="muted">Signal Sentinel</p>
          <h1>Hot data into decision-grade signals</h1>
          <p>
            Collect X, web, news, and market observations. Quantify them into a small typed format the trading
            agents can consume without reading a noisy feed.
          </p>
        </div>
        <div className="signal-kpis">
          <div>
            <strong>{stats.watch}</strong>
            <span>active signals</span>
          </div>
          <div>
            <strong>{stats.highUrgency}</strong>
            <span>high urgency</span>
          </div>
          <div>
            <strong>{stats.avgConfidence.toFixed(2)}</strong>
            <span>avg confidence</span>
          </div>
        </div>
      </section>

      <section className="signal-pipeline">
        {["Observe", "Standardize", "Validate", "Feed agents"].map((step) => (
          <span key={step}>{step}</span>
        ))}
      </section>

      <section className="ops-grid">
        <article className="panel">
          <div className="section-header">
            <div>
              <h3>Live Signal Feed</h3>
              <p className="muted">Small, typed, and auditable. No raw feed noise by default.</p>
            </div>
            <span className="badge badge-neutral">{signals.length}</span>
          </div>
          <div className="signal-feed">
            {signals.length === 0 && <p className="muted">No signals yet. Capture one manually or wire the Sentinel scheduler.</p>}
            {signals.map((signal) => (
              <article key={signal.id} className={`signal-card ${toneForDirection(signal.direction)}`}>
                <div className="signal-card-head">
                  <div>
                    <strong>{signal.asset}{signal.symbol ? ` · ${signal.symbol}` : ""}</strong>
                    <span className="muted">{signal.topic}</span>
                  </div>
                  <span className="badge badge-neutral">{signal.status}</span>
                </div>
                <p>{signal.summary}</p>
                <div className="signal-metrics">
                  <span>{signal.direction}</span>
                  <span>sentiment {scoreLabel(signal.sentimentScore)}</span>
                  <span>confidence {signal.confidence.toFixed(2)}</span>
                  <span>{signal.urgency}</span>
                </div>
                {signal.reasoningSummary && (
                  <details className="signal-audit">
                    <summary>Audit trail</summary>
                    <p>{signal.reasoningSummary}</p>
                    <pre>{JSON.stringify(signal.evidenceJson, null, 2)}</pre>
                  </details>
                )}
              </article>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="section-header">
            <div>
              <h3>QA Capture</h3>
              <p className="muted">Manual path for testing the standardized format before automation.</p>
            </div>
          </div>
          <form className="research-command" onSubmit={submitSignal}>
            <label className="field signal-mode-toggle">
              <span>Formatter</span>
              <button className="btn btn-secondary" type="button" onClick={() => setUseLLMFormat((value) => !value)}>
                {useLLMFormat ? "LLM formatter on" : "Manual formatter"}
              </button>
            </label>
            <div className="form-grid-two">
              <label className="field">
                <span>Source</span>
                <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as RawObservation["sourceKind"])}>
                  <option value="manual">manual</option>
                  <option value="x">x</option>
                  <option value="web">web</option>
                  <option value="news">news</option>
                  <option value="market">market</option>
                </select>
              </label>
              <label className="field">
                <span>Source name</span>
                <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
              </label>
            </div>
            <label className="field">
              <span>Observation title</span>
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="ETF inflow spike, X narrative, funding shift..." />
            </label>
            <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={4} placeholder="Raw observation text or pasted source excerpt" />
            {!useLLMFormat && (
            <div className="form-grid-two">
              <label className="field">
                <span>Asset</span>
                <input value={asset} onChange={(event) => setAsset(event.target.value)} />
              </label>
              <label className="field">
                <span>Symbol</span>
                <input value={symbol} onChange={(event) => setSymbol(event.target.value)} />
              </label>
              <label className="field">
                <span>Direction</span>
                <select value={direction} onChange={(event) => setDirection(event.target.value as StandardizedSignal["direction"])}>
                  <option value="bullish">bullish</option>
                  <option value="bearish">bearish</option>
                  <option value="neutral">neutral</option>
                  <option value="mixed">mixed</option>
                </select>
              </label>
              <label className="field">
                <span>Urgency</span>
                <select value={urgency} onChange={(event) => setUrgency(event.target.value as StandardizedSignal["urgency"])}>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
            </div>
            )}
            {!useLLMFormat && (
            <label className="field">
              <span>Confidence {confidence.toFixed(2)}</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={confidence}
                onChange={(event) => setConfidence(Number(event.target.value))}
              />
            </label>
            )}
            {!useLLMFormat && (
              <textarea value={summary} onChange={(event) => setSummary(event.target.value)} rows={3} placeholder="Decision-grade signal summary" />
            )}
            <div className="command-panel-footer">
              <span className="field-help">
                {useLLMFormat ? "Uses the latest model profile and stores the standardized signal." : "Manual path writes the same shape as automation."}
              </span>
              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting ? "Capturing..." : useLLMFormat ? "Format with LLM" : "Capture signal"}
              </button>
            </div>
            {error && <p className="feedback feedback-error">{error}</p>}
          </form>
        </article>
      </section>

      <section className="panel">
        <div className="section-header">
          <h3>Recent Observations</h3>
          <span className="badge badge-neutral">{observations.length}</span>
        </div>
        <div className="dense-list">
          {observations.length === 0 && <p className="muted">No raw observations captured yet.</p>}
          {observations.map((observation) => (
            <div key={observation.id} className="dense-row">
              <span>
                <strong>{observation.title}</strong>
                <span className="muted">
                  {observation.sourceKind} · {observation.sourceName} · <LocalTime value={observation.observedAt} />
                </span>
              </span>
              <span className="badge badge-neutral">raw</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
