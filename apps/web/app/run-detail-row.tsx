"use client";

import { Fragment, useState, useEffect } from "react";
import { LocalTime } from "./local-time";

type RunRow = {
  id: string;
  botName: string;
  status: string;
  startedAt: string;
  decisionMode: string | null;
  rationaleSummary: string | null;
};

type RunDetail = {
  promptSystem: string | null;
  promptUser: string | null;
  researchOutput: string | null;
  traderOutput: string | null;
  parsedDecision: Record<string, unknown> | null;
  validationResult: { accepted: boolean; issues: string[] } | null;
};

type ToolCall = {
  tool: string;
  input: unknown;
  output: unknown;
  latencyMs: number;
  error: string | null;
};

type LLMCall = {
  id: string;
  phase: string;
  provider: string;
  model: string;
  inputTokens: number | null;
  outputTokens: number | null;
  latencyMs: number | null;
  attempt: number;
  strategy: string | null;
  error: string | null;
  createdAt: string;
  toolCalls: ToolCall[] | null;
  iterations: number | null;
};

/* ── Phase splitting logic (shared with bot-detail RunDetail) ── */

const PHASE_MARKERS = {
  system: {
    p1: "=== PHASE 1 — RESEARCH (system) ===",
    p2: "=== PHASE 2 — TRADER (system) ==="
  },
  user: {
    p1: "=== PHASE 1 — RESEARCH (user context) ===",
    p2: "=== PHASE 2 — TRADER (user context) ==="
  }
} as const;

function normalizePhaseHeaders(text: string) {
  return text
    .replaceAll("=== PHASE 1 - RESEARCH", "=== PHASE 1 — RESEARCH")
    .replaceAll("=== PHASE 2 - FORMATTER", "=== PHASE 2 — TRADER")
    .replaceAll("=== PHASE 2 — FORMATTER", "=== PHASE 2 — TRADER");
}

function splitPhases(text: string | null, markers: { p1: string; p2: string }) {
  if (!text) return { phase1: null, phase2: null };
  const normalized = normalizePhaseHeaders(text);
  const p2Idx = normalized.indexOf(markers.p2);
  if (p2Idx === -1) return { phase1: normalized.trim(), phase2: null };
  const phase1 = normalized.slice(0, p2Idx).replace(markers.p1, "").trim();
  const phase2 = normalized.slice(p2Idx).replace(markers.p2, "").trim();
  return { phase1: phase1 || null, phase2: phase2 || null };
}

/* ── Reusable sub-components ── */

function PhaseBlock({ label, content, defaultHidden = false }: { label: string; content: string | null; defaultHidden?: boolean }) {
  const [visible, setVisible] = useState(!defaultHidden);
  if (!content) return null;
  return (
    <div style={{ marginTop: "12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
        <p className="label" style={{ margin: 0 }}>{label}</p>
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="toggle-btn"
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {visible && <pre className="run-detail-pre">{content}</pre>}
    </div>
  );
}

function PipelineSteps({ detail, llmCalls }: { detail: RunDetail; llmCalls: LLMCall[] | null }) {
  const systemParts = splitPhases(detail.promptSystem, PHASE_MARKERS.system);
  const hasPhase1 = !!(systemParts.phase1 || detail.researchOutput);
  const hasPhase2 = !!(systemParts.phase2 || detail.traderOutput);
  const validationOk = detail.validationResult ? detail.validationResult.accepted : null;

  const researchCalls = llmCalls?.filter((c) => c.phase === "research") ?? [];
  const traderCalls = llmCalls?.filter((c) => c.phase === "trader") ?? [];

  const steps = [
    {
      key: "research",
      label: "Research",
      color: "#a78bfa",
      active: hasPhase1,
      failed: researchCalls.some((c) => c.error),
      tokens: researchCalls.reduce((s, c) => s + (c.inputTokens ?? 0) + (c.outputTokens ?? 0), 0),
      latency: researchCalls.reduce((s, c) => s + (c.latencyMs ?? 0), 0)
    },
    {
      key: "trader",
      label: "Trader",
      color: "#34d399",
      active: hasPhase2,
      failed: traderCalls.some((c) => c.error),
      tokens: traderCalls.reduce((s, c) => s + (c.inputTokens ?? 0) + (c.outputTokens ?? 0), 0),
      latency: traderCalls.reduce((s, c) => s + (c.latencyMs ?? 0), 0)
    },
    {
      key: "validator",
      label: "Validator",
      color: validationOk === false ? "#f87171" : "#60a5fa",
      active: validationOk !== null,
      failed: validationOk === false,
      tokens: 0,
      latency: 0
    }
  ];

  const totalTokens = steps.reduce((s, step) => s + step.tokens, 0);
  const totalLatency = steps.reduce((s, step) => s + step.latency, 0);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0", marginBottom: "16px", flexWrap: "wrap" }}>
      {steps.map((step, i) => (
        <div key={step.key} style={{ display: "flex", alignItems: "center" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: 600,
              background: step.active ? `${step.color}1a` : "#27272a",
              border: `1px solid ${step.active ? `${step.color}44` : "#3f3f46"}`,
              color: step.active ? step.color : "#52525b",
              opacity: step.active ? 1 : 0.5
            }}
          >
            <span style={{ fontSize: "10px" }}>
              {step.failed ? "✕" : step.active ? "✓" : "○"}
            </span>
            {step.label}
            {step.tokens > 0 && (
              <span style={{ fontSize: "10px", opacity: 0.7 }}>{step.tokens.toLocaleString()} tok</span>
            )}
          </div>
          {i < steps.length - 1 && (
            <span style={{ color: "#3f3f46", margin: "0 4px", fontSize: "12px" }}>→</span>
          )}
        </div>
      ))}
      {totalTokens > 0 && (
        <span style={{ marginLeft: "12px", fontSize: "11px", color: "#71717a" }}>
          {totalTokens.toLocaleString()} total tok
          {totalLatency > 0 && ` · ${(totalLatency / 1000).toFixed(1)}s`}
        </span>
      )}
    </div>
  );
}

function ValidationBanner({ result }: { result: { accepted: boolean; issues: string[] } }) {
  if (result.accepted) return null;
  return (
    <div style={{
      marginBottom: "12px",
      background: "#451a1a",
      border: "1px solid #7f1d1d",
      borderRadius: "6px",
      padding: "10px 12px",
      fontSize: "12px"
    }}>
      <p style={{ color: "#fca5a5", fontWeight: 600, margin: "0 0 4px 0" }}>Validation rejected</p>
      {result.issues.map((issue, i) => (
        <p key={i} style={{ color: "#fca5a5", margin: "2px 0", fontSize: "11px" }}>{issue}</p>
      ))}
    </div>
  );
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function ToolCallsList({ calls }: { calls: ToolCall[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div style={{ marginTop: "6px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ fontSize: "11px", fontWeight: 600, color: "#60a5fa" }}>
          Tool calls ({calls.length})
        </span>
        <button type="button" onClick={() => setExpanded((v) => !v)} className="toggle-btn">
          {expanded ? "Hide" : "Show"}
        </button>
      </div>
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "6px" }}>
          {calls.map((c, i) => (
            <div
              key={i}
              style={{
                background: "#1e1e21",
                border: "1px solid #27272a",
                borderRadius: "4px",
                padding: "8px 10px",
                fontSize: "11px",
                borderLeft: c.error ? "3px solid #ef4444" : "3px solid #60a5fa"
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontWeight: 600, fontFamily: "monospace" }}>{c.tool}</span>
                <span className="muted">{c.latencyMs}ms</span>
              </div>
              <div style={{ marginBottom: "4px" }}>
                <span className="muted" style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.04em" }}>Input</span>
                <pre style={{
                  background: "#27272a", padding: "6px 8px", borderRadius: "4px",
                  fontSize: "11px", margin: "2px 0 0", maxHeight: "160px", overflow: "auto",
                  whiteSpace: "pre-wrap"
                }}>{formatJson(c.input)}</pre>
              </div>
              <div>
                <span className="muted" style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.04em" }}>Output</span>
                <pre style={{
                  background: "#27272a", padding: "6px 8px", borderRadius: "4px",
                  fontSize: "11px", margin: "2px 0 0", maxHeight: "240px", overflow: "auto",
                  whiteSpace: "pre-wrap"
                }}>{formatJson(c.output)}</pre>
              </div>
              {c.error && (
                <div style={{ color: "#ef4444", marginTop: "4px", fontSize: "11px" }}>{c.error}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LLMCallsPanel({ calls }: { calls: LLMCall[] }) {
  const [expanded, setExpanded] = useState(false);
  if (calls.length === 0) return null;

  return (
    <div style={{ marginTop: "16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <p style={{ fontWeight: 600, fontSize: "13px", color: "#fbbf24", margin: 0 }}>
          LLM Calls ({calls.length})
        </p>
        <button type="button" onClick={() => setExpanded((v) => !v)} className="toggle-btn">
          {expanded ? "Hide" : "Show"}
        </button>
      </div>
      {expanded && (
        <div style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "8px" }}>
          {calls.map((call) => (
            <div
              key={call.id}
              style={{
                background: "#27272a",
                padding: "10px 12px",
                borderRadius: "6px",
                fontSize: "12px",
                borderLeft: call.error
                  ? "3px solid #ef4444"
                  : call.phase === "research"
                    ? "3px solid #a78bfa"
                    : "3px solid #34d399"
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontWeight: 600, textTransform: "capitalize" }}>
                  {call.phase}
                  {call.attempt > 1 && <span style={{ color: "#fbbf24" }}> (attempt {call.attempt})</span>}
                </span>
                <span className="muted">{call.provider}/{call.model}</span>
              </div>
              <div style={{ display: "flex", gap: "16px", color: "#a1a1aa", flexWrap: "wrap" }}>
                {call.inputTokens != null && <span>In: {call.inputTokens.toLocaleString()} tok</span>}
                {call.outputTokens != null && <span>Out: {call.outputTokens.toLocaleString()} tok</span>}
                {call.latencyMs != null && <span>{(call.latencyMs / 1000).toFixed(1)}s</span>}
                {call.strategy && <span>Strategy: {call.strategy}</span>}
                {call.iterations != null && <span>Iterations: {call.iterations}</span>}
              </div>
              {call.error && (
                <div style={{ color: "#ef4444", marginTop: "4px", fontSize: "11px" }}>{call.error}</div>
              )}
              {Array.isArray(call.toolCalls) && call.toolCalls.length > 0 && (
                <ToolCallsList calls={call.toolCalls} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RunDetailExpanded({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [llmCalls, setLlmCalls] = useState<LLMCall[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`/api/runs/${runId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/runs/${runId}/llm-calls`).then((r) => r.ok ? r.json() : []).then((d) => Array.isArray(d) ? d : d?.calls ?? []).catch(() => [])
    ])
      .then(([d, calls]) => {
        setDetail(d);
        setLlmCalls(Array.isArray(calls) ? calls : []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <p className="muted">Loading run details...</p>;
  if (!detail) return <p className="muted">Could not load details.</p>;

  const systemParts = splitPhases(detail.promptSystem, PHASE_MARKERS.system);
  const userParts = splitPhases(detail.promptUser, PHASE_MARKERS.user);

  return (
    <div className="run-detail-panels">
      {/* Pipeline visualization */}
      <PipelineSteps detail={detail} llmCalls={llmCalls} />

      {/* Validation failure banner */}
      {detail.validationResult && !detail.validationResult.accepted && (
        <ValidationBanner result={detail.validationResult} />
      )}

      {/* View mode toggle */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
        <button
          type="button"
          className={`btn ${!showRaw ? "btn-primary" : ""}`}
          style={{ fontSize: "0.75rem", padding: "6px 12px" }}
          onClick={() => setShowRaw(false)}
        >
          Structured
        </button>
        <button
          type="button"
          className={`btn ${showRaw ? "btn-primary" : ""}`}
          style={{ fontSize: "0.75rem", padding: "6px 12px" }}
          onClick={() => setShowRaw(true)}
        >
          Raw
        </button>
      </div>

      {showRaw ? (
        <>
          <div className="run-detail-panel">
            <h4>System Prompt (full)</h4>
            <pre className="run-detail-pre">{detail.promptSystem || "Not recorded"}</pre>
          </div>
          <div className="run-detail-panel">
            <h4>User Message (full)</h4>
            <pre className="run-detail-pre">{detail.promptUser || "Not recorded"}</pre>
          </div>
        </>
      ) : (
        <>
          {/* Phase 1: Research */}
          {(systemParts.phase1 || userParts.phase1) && (
            <div className="run-detail-panel">
              <h4 style={{ color: "#a78bfa" }}>Phase 1 — Research</h4>
              <PhaseBlock label="System prompt" content={systemParts.phase1} />
              <PhaseBlock label="User context" content={userParts.phase1} />
            </div>
          )}

          {/* Phase 2: Trader */}
          {(systemParts.phase2 || userParts.phase2) && (
            <div className="run-detail-panel">
              <h4 style={{ color: "#34d399" }}>Phase 2 — Trader</h4>
              <PhaseBlock label="System prompt" content={systemParts.phase2} defaultHidden />
              <PhaseBlock label="User context" content={userParts.phase2} />
            </div>
          )}

          {/* Fallback for old single-phase runs */}
          {!systemParts.phase1 && !systemParts.phase2 && (
            <div className="run-detail-panel">
              <h4>System Prompt</h4>
              <pre className="run-detail-pre">{detail.promptSystem || "Not recorded"}</pre>
            </div>
          )}
          {!userParts.phase1 && !userParts.phase2 && (
            <div className="run-detail-panel">
              <h4>User Context</h4>
              <pre className="run-detail-pre">{detail.promptUser || "Not recorded"}</pre>
            </div>
          )}
        </>
      )}

      {/* Model outputs — always show both phases separately */}
      <div className="run-detail-panel">
        <h4 style={{ color: "#a78bfa" }}>Research output</h4>
        <pre className="run-detail-pre">
          {detail.researchOutput ? tryFormatJson(detail.researchOutput) : "Not recorded"}
        </pre>
      </div>
      <div className="run-detail-panel">
        <h4 style={{ color: "#34d399" }}>Trader output</h4>
        <pre className="run-detail-pre" style={{ maxHeight: "400px" }}>
          {detail.traderOutput ? tryFormatJson(detail.traderOutput) : "Not recorded"}
        </pre>
      </div>

      {/* LLM Calls */}
      {llmCalls && llmCalls.length > 0 && <LLMCallsPanel calls={llmCalls} />}
    </div>
  );
}

export function RecentRunsTable({ runs }: { runs: RunRow[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Bot</th>
          <th>Status</th>
          <th>Started</th>
          <th>Mode</th>
          <th>Summary</th>
          <th style={{ width: 40 }} />
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <Fragment key={run.id}>
            <tr
              className={`run-row ${expandedId === run.id ? "run-row-expanded" : ""}`}
              onClick={() => setExpandedId(expandedId === run.id ? null : run.id)}
              style={{ cursor: "pointer" }}
            >
              <td>{run.botName}</td>
              <td><span className={`badge badge-${run.status}`}>{run.status}</span></td>
              <td><LocalTime value={run.startedAt} /></td>
              <td>{run.decisionMode ?? "-"}</td>
              <td className="run-summary-cell">{run.rationaleSummary ?? "-"}</td>
              <td className="run-expand-icon">{expandedId === run.id ? "▾" : "▸"}</td>
            </tr>
            {expandedId === run.id && (
              <tr key={`${run.id}-detail`} className="run-detail-row">
                <td colSpan={6}>
                  <RunDetailExpanded runId={run.id} />
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function tryFormatJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
