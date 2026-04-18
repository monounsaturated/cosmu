"use client";

import { useState, useEffect } from "react";
import { LocalTime } from "../../local-time";

type Run = {
  id: string;
  status: string;
  startedAt: string;
  promptSystem: string | null;
  promptUser: string | null;
  researchOutput: string | null;
  traderOutput: string | null;
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

/* ── Phase splitting ── */

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

/* ── User context section splitting ── */

const SECTION_MARKERS = [
  "=== SESSION ===",
  "=== WALLET ===",
  "=== TRADING SCOPE ===",
  "=== PORTFOLIO OVERVIEW ===",
  "=== PERFORMANCE STATS ===",
  "=== EXECUTION RULES ===",
  "=== LIVE MARKET PRICES",
  "=== UPSTREAM RESEARCH",
];

type ParsedInput = {
  writtenPrompt: string | null;
  sections: { label: string; content: string }[];
};

/** System prompt is just the user's written prompt (no preamble). */
function parseSystemPrompt(text: string | null): string | null {
  if (!text) return null;
  return text.trim() || null;
}

/** Split user context into labelled sections (SESSION, WALLET, etc.) */
function parseUserContext(text: string | null): ParsedInput {
  if (!text) return { writtenPrompt: null, sections: [] };

  const sections: { label: string; content: string }[] = [];
  const lines = text.split("\n");
  let currentLabel: string | null = null;
  let currentLines: string[] = [];
  let prelude: string[] = [];

  for (const line of lines) {
    const markerMatch = SECTION_MARKERS.find((m) => line.trim().startsWith(m));
    if (markerMatch) {
      // Flush previous section
      if (currentLabel) {
        sections.push({ label: currentLabel, content: currentLines.join("\n").trim() });
      }
      // Extract label from the === LABEL === format
      const labelMatch = line.trim().match(/^===\s*(.+?)\s*===$/);
      let rawLabel = labelMatch ? labelMatch[1] : line.trim().replace(/^===\s*/, "").replace(/\s*===$/, "");
      if (/^UPSTREAM RESEARCH/i.test(rawLabel)) rawLabel = "Research Output";
      currentLabel = rawLabel;
      currentLines = [];
    } else if (currentLabel) {
      currentLines.push(line);
    } else {
      prelude.push(line);
    }
  }

  // Flush last section
  if (currentLabel) {
    sections.push({ label: currentLabel, content: currentLines.join("\n").trim() });
  }

  return {
    writtenPrompt: prelude.join("\n").trim() || null,
    sections
  };
}

/* ── Styles ── */

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

const sectionTagStyle = {
  display: "inline-block" as const,
  fontSize: "10px",
  fontWeight: 600 as const,
  textTransform: "uppercase" as const,
  letterSpacing: "0.05em",
  padding: "2px 8px",
  borderRadius: "4px",
  marginBottom: "6px"
};

/* ── Sub-components ── */

function ToggleButton({ visible, onClick }: { visible: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="toggle-btn">
      {visible ? "Hide" : "Show"}
    </button>
  );
}

function PhaseBlock({ label, content, defaultHidden = false }: { label: string; content: string | null; defaultHidden?: boolean }) {
  const [visible, setVisible] = useState(!defaultHidden);
  if (!content) return null;
  return (
    <div style={{ marginTop: "16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
        <p className="label" style={{ margin: 0 }}>{label}</p>
        <ToggleButton visible={visible} onClick={() => setVisible((v) => !v)} />
      </div>
      {visible && <pre style={preStyle}>{content}</pre>}
    </div>
  );
}

function InputBreakdown({ systemPrompt, userContext, phaseLabel, phaseColor, rawOutput, outputLabel }: {
  systemPrompt: string | null;
  userContext: string | null;
  phaseLabel: string;
  phaseColor: string;
  rawOutput?: string | null;
  outputLabel?: string;
}) {
  const [showSections, setShowSections] = useState(false);

  const writtenPrompt = parseSystemPrompt(systemPrompt);
  const { sections } = parseUserContext(userContext);

  return (
    <div style={{ marginTop: "20px" }}>
      <p style={{ fontWeight: 600, fontSize: "13px", color: phaseColor, marginBottom: "8px" }}>
        {phaseLabel}
      </p>

      {writtenPrompt && (
        <div style={{ marginBottom: "12px" }}>
          <span style={{ ...sectionTagStyle, background: `${phaseColor}1a`, color: phaseColor }}>Written Prompt</span>
          <pre style={{ ...preStyle, borderLeft: `3px solid ${phaseColor}` }}>{writtenPrompt}</pre>
        </div>
      )}

      {sections.length > 0 && (
        <div style={{ marginBottom: "12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
            <span style={{ ...sectionTagStyle, background: "#34d3991a", color: "#34d399" }}>
              Injected Data ({sections.length} sections)
            </span>
            <ToggleButton visible={showSections} onClick={() => setShowSections((v) => !v)} />
          </div>
          {showSections && (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {sections.map((section, i) => (
                <div key={i} style={{ background: "#1e1e21", border: "1px solid #27272a", borderRadius: "6px", overflow: "hidden" }}>
                  <div style={{ padding: "6px 10px", background: "#27272a", fontSize: "11px", fontWeight: 600, color: "#a1a1aa", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    {section.label}
                  </div>
                  <pre style={{ ...preStyle, background: "transparent", borderRadius: 0, maxHeight: "200px", margin: 0 }}>
                    {section.content}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {rawOutput !== undefined && (
        <div style={{ marginTop: "16px" }}>
          <p style={{ fontWeight: 600, fontSize: "13px", color: phaseColor, marginBottom: "4px" }}>
            {outputLabel ?? "Model Output"}
          </p>
          <pre style={{ ...preStyle, maxHeight: "400px" }}>{rawOutput ? tryFormatJson(rawOutput) : "Not recorded"}</pre>
        </div>
      )}
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
      .then((data) => setCalls(Array.isArray(data) ? data : data?.calls ?? []))
      .catch(() => setCalls([]))
      .finally(() => setLoading(false));
  }, [expanded, runId, calls]);

  return (
    <div style={{ marginTop: "20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <p style={{ fontWeight: 600, fontSize: "13px", color: "#fbbf24", margin: 0 }}>
          LLM Calls
        </p>
        <ToggleButton visible={expanded} onClick={() => setExpanded((v) => !v)} />
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

/* ── Main component ── */

export function RunDetail({ run }: { run: Run }) {
  const [showRaw, setShowRaw] = useState(false);

  const systemParts = splitPhases(run.promptSystem, PHASE_MARKERS.system);
  const userParts = splitPhases(run.promptUser, PHASE_MARKERS.user);
  const hasTwoPhases = !!(systemParts.phase2 || userParts.phase2);

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
          <div style={{ marginTop: "16px" }}>
            <p className="label">Research Output (full)</p>
            <pre style={preStyle}>{run.researchOutput || "Not recorded"}</pre>
          </div>
          <div style={{ marginTop: "16px" }}>
            <p className="label">Trader Output (full)</p>
            <pre style={preStyle}>{run.traderOutput || "Not recorded"}</pre>
          </div>
        </>
      ) : hasTwoPhases ? (
        <>
          <InputBreakdown
            systemPrompt={systemParts.phase1}
            userContext={userParts.phase1}
            phaseLabel="Phase 1 — Research"
            phaseColor="#a78bfa"
            rawOutput={run.researchOutput}
            outputLabel="Research Model Output"
          />
          <InputBreakdown
            systemPrompt={systemParts.phase2}
            userContext={userParts.phase2}
            phaseLabel="Phase 2 — Trader"
            phaseColor="#34d399"
            rawOutput={run.traderOutput}
            outputLabel="Trader Model Output"
          />
        </>
      ) : (
        <>
          <InputBreakdown
            systemPrompt={run.promptSystem}
            userContext={run.promptUser}
            phaseLabel="Research"
            phaseColor="#a78bfa"
            rawOutput={run.researchOutput ?? run.traderOutput}
            outputLabel="Model Output"
          />
        </>
      )}

      {/* LLM Calls */}
      <LLMCallsPanel runId={run.id} />
    </details>
  );
}

function tryFormatJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
