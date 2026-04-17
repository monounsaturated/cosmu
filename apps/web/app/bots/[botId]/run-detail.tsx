"use client";

import { useState, useEffect } from "react";
import { LocalTime } from "../../local-time";

type Run = {
  id: string;
  status: string;
  startedAt: string;
  promptSystem: string | null;
  promptUser: string | null;
  rawModelOutput: string | null;
  formatterVersion: number | null;
  validationResult?: { accepted: boolean; issues: string[] } | null;
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
};

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

/** Older runs used ASCII hyphen or "FORMATTER" in phase headers. */
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

/** Parse stored raw output — may be JSON with phase1Research / phase2Trader keys. */
function splitRawOutput(raw: string | null): { phase1: string | null; phase2: string | null } {
  if (!raw) return { phase1: null, phase2: null };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && (parsed.phase1Research !== undefined || parsed.phase2Trader !== undefined || parsed.phase2Decision !== undefined)) {
      return {
        phase1: parsed.phase1Research ?? null,
        phase2: parsed.phase2Trader ?? parsed.phase2Decision ?? null
      };
    }
  } catch {
    // not JSON — treat as legacy single-phase output
  }
  return { phase1: raw, phase2: null };
}

const preStyle = {
  background: "#27272a",
  padding: "12px",
  borderRadius: "4px",
  fontSize: "12px",
  overflowX: "auto" as const,
  whiteSpace: "pre-wrap" as const,
  maxHeight: "300px",
  overflowY: "auto" as const
};

function PhaseBlock({
  label,
  content,
  defaultHidden = false
}: {
  label: string;
  content: string | null;
  defaultHidden?: boolean;
}) {
  const [visible, setVisible] = useState(!defaultHidden);
  if (!content) return null;
  return (
    <div style={{ marginTop: "16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
        <p className="label" style={{ margin: 0 }}>{label}</p>
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          style={{
            background: "none",
            border: "1px solid #3f3f46",
            borderRadius: "4px",
            color: "#a1a1aa",
            cursor: "pointer",
            fontSize: "11px",
            padding: "1px 6px",
            lineHeight: 1.4
          }}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {visible && <pre style={preStyle}>{content}</pre>}
    </div>
  );
}

function LLMCallsPanel({ runId }: { runId: string }) {
  const [calls, setCalls] = useState<LLMCall[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded || calls) return;
    setLoading(true);
    fetch(`/api/runs/${runId}/llm-calls`)
      .then((res) => res.ok ? res.json() : [])
      .then((data) => setCalls(Array.isArray(data) ? data : []))
      .catch(() => setCalls([]))
      .finally(() => setLoading(false));
  }, [expanded, runId, calls]);

  return (
    <div style={{ marginTop: "20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <p style={{ fontWeight: 600, fontSize: "13px", color: "#fbbf24", margin: 0 }}>
          LLM Calls
        </p>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          style={{
            background: "none",
            border: "1px solid #3f3f46",
            borderRadius: "4px",
            color: "#a1a1aa",
            cursor: "pointer",
            fontSize: "11px",
            padding: "1px 6px",
            lineHeight: 1.4
          }}
        >
          {expanded ? "Hide" : "Show"}
        </button>
      </div>
      {expanded && (
        <div style={{ marginTop: "8px" }}>
          {loading && <p className="muted">Loading...</p>}
          {calls && calls.length === 0 && <p className="muted">No LLM calls recorded for this run.</p>}
          {calls && calls.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {calls.map((call) => (
                <div
                  key={call.id}
                  style={{
                    background: "#27272a",
                    padding: "10px 12px",
                    borderRadius: "6px",
                    fontSize: "12px",
                    borderLeft: call.error ? "3px solid #ef4444" : call.phase === "research" ? "3px solid #a78bfa" : "3px solid #34d399"
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                    <span style={{ fontWeight: 600, textTransform: "capitalize" }}>
                      {call.phase}
                      {call.attempt > 1 && <span style={{ color: "#fbbf24" }}> (attempt {call.attempt})</span>}
                    </span>
                    <span className="muted">{call.provider}/{call.model}</span>
                  </div>
                  <div style={{ display: "flex", gap: "16px", color: "#a1a1aa" }}>
                    {call.inputTokens != null && <span>In: {call.inputTokens.toLocaleString()} tok</span>}
                    {call.outputTokens != null && <span>Out: {call.outputTokens.toLocaleString()} tok</span>}
                    {call.latencyMs != null && <span>{(call.latencyMs / 1000).toFixed(1)}s</span>}
                    {call.strategy && <span>Strategy: {call.strategy}</span>}
                  </div>
                  {call.error && (
                    <div style={{ color: "#ef4444", marginTop: "4px", fontSize: "11px" }}>{call.error}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function RunDetail({ run }: { run: Run }) {
  const [showRaw, setShowRaw] = useState(false);

  const systemParts = splitPhases(run.promptSystem, PHASE_MARKERS.system);
  const userParts = splitPhases(run.promptUser, PHASE_MARKERS.user);
  const rawParts = splitRawOutput(run.rawModelOutput);

  const validationFailed = run.validationResult && !run.validationResult.accepted;

  return (
    <details style={{ background: "#18181b", padding: "16px", borderRadius: "8px" }}>
      <summary style={{ cursor: "pointer", fontWeight: "bold" }}>
        <LocalTime value={run.startedAt} /> - <span className={`badge badge-${run.status}`}>{run.status}</span>
        {run.formatterVersion && (
          <span className="badge badge-neutral" style={{ marginLeft: "8px" }}>formatter v{run.formatterVersion}</span>
        )}
      </summary>

      {/* Validation failure banner */}
      {validationFailed && (
        <div style={{
          marginTop: "12px",
          background: "#451a1a",
          border: "1px solid #7f1d1d",
          borderRadius: "6px",
          padding: "10px 12px",
          fontSize: "12px"
        }}>
          <p style={{ color: "#fca5a5", fontWeight: 600, margin: "0 0 4px 0" }}>Validation rejected</p>
          {run.validationResult!.issues.map((issue, i) => (
            <p key={i} style={{ color: "#fca5a5", margin: "2px 0", fontSize: "11px" }}>{issue}</p>
          ))}
        </div>
      )}

      <div style={{ marginTop: "12px", display: "flex", gap: "8px" }}>
        <button
          type="button"
          className={`btn ${!showRaw ? "btn-primary" : ""}`}
          style={{ fontSize: "0.75rem" }}
          onClick={() => setShowRaw(false)}
        >
          Structured
        </button>
        <button
          type="button"
          className={`btn ${showRaw ? "btn-primary" : ""}`}
          style={{ fontSize: "0.75rem" }}
          onClick={() => setShowRaw(true)}
        >
          Raw
        </button>
      </div>

      {showRaw ? (
        <>
          <div style={{ marginTop: "16px" }}>
            <p className="label">System Prompt (full)</p>
            <pre style={preStyle}>{run.promptSystem || "Not recorded"}</pre>
          </div>
          <div style={{ marginTop: "16px" }}>
            <p className="label">User Message (full)</p>
            <pre style={preStyle}>{run.promptUser || "Not recorded"}</pre>
          </div>
        </>
      ) : (
        <>
          {/* Phase 1: Research */}
          {(systemParts.phase1 || userParts.phase1) && (
            <div style={{ marginTop: "20px" }}>
              <p style={{ fontWeight: 600, fontSize: "13px", color: "#a78bfa", marginBottom: "4px" }}>
                Phase 1 — Research
              </p>
              <PhaseBlock label="System prompt" content={systemParts.phase1} />
              <PhaseBlock label="User context" content={userParts.phase1} />
            </div>
          )}

          {/* Phase 2: Trader */}
          {(systemParts.phase2 || userParts.phase2) && (
            <div style={{ marginTop: "20px" }}>
              <p style={{ fontWeight: 600, fontSize: "13px", color: "#34d399", marginBottom: "4px" }}>
                Phase 2 — Trader
              </p>
              <PhaseBlock label="System prompt" content={systemParts.phase2} defaultHidden={true} />
              <PhaseBlock label="User context" content={userParts.phase2} />
            </div>
          )}

          {/* Fallback for old single-phase runs */}
          {!systemParts.phase1 && !systemParts.phase2 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">System Prompt</p>
              <pre style={preStyle}>{run.promptSystem || "Not recorded"}</pre>
            </div>
          )}
          {!userParts.phase1 && !userParts.phase2 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">User Context</p>
              <pre style={preStyle}>{run.promptUser || "Not recorded"}</pre>
            </div>
          )}
        </>
      )}

      {/* Model outputs */}
      <div style={{ marginTop: "20px" }}>
        {rawParts.phase2 ? (
          <>
            <div>
              <p style={{ fontWeight: 600, fontSize: "13px", color: "#a78bfa", marginBottom: "4px" }}>
                Research output
              </p>
              <pre style={{ ...preStyle, maxHeight: "300px" }}>{rawParts.phase1 || "Not recorded"}</pre>
            </div>
            <div style={{ marginTop: "16px" }}>
              <p style={{ fontWeight: 600, fontSize: "13px", color: "#34d399", marginBottom: "4px" }}>
                Trader decision
              </p>
              <pre style={{ ...preStyle, maxHeight: "400px" }}>{rawParts.phase2}</pre>
            </div>
          </>
        ) : (
          <div>
            <p className="label">Raw Model Output</p>
            <pre style={{ ...preStyle, maxHeight: "400px" }}>
              {run.rawModelOutput || "Not recorded"}
            </pre>
          </div>
        )}
      </div>

      {/* LLM Calls */}
      <LLMCallsPanel runId={run.id} />
    </details>
  );
}
