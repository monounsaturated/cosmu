"use client";

import { useState } from "react";
import { LocalTime } from "../../local-time";

type Run = {
  id: string;
  status: string;
  startedAt: string;
  promptSystem: string | null;
  promptUser: string | null;
  rawModelOutput: string | null;
  formatterVersion: number | null;
};

const PHASE_MARKERS = {
  system: {
    p1: "=== PHASE 1 — RESEARCH (system) ===",
    p2: "=== PHASE 2 — FORMATTER (system) ==="
  },
  user: {
    p1: "=== PHASE 1 — RESEARCH (user context) ===",
    p2: "=== PHASE 2 — FORMATTER (user context) ==="
  }
} as const;

/** Older runs used ASCII hyphen in phase headers instead of em dash. */
function normalizePhaseHeaders(text: string) {
  return text
    .replaceAll("=== PHASE 1 - RESEARCH", "=== PHASE 1 — RESEARCH")
    .replaceAll("=== PHASE 2 - FORMATTER", "=== PHASE 2 — FORMATTER");
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

export function RunDetail({ run }: { run: Run }) {
  const [showRaw, setShowRaw] = useState(false);

  const systemParts = splitPhases(run.promptSystem, PHASE_MARKERS.system);
  const userParts = splitPhases(run.promptUser, PHASE_MARKERS.user);

  return (
    <details style={{ background: "#18181b", padding: "16px", borderRadius: "8px" }}>
      <summary style={{ cursor: "pointer", fontWeight: "bold" }}>
        <LocalTime value={run.startedAt} /> - <span className={`badge badge-${run.status}`}>{run.status}</span>
        {run.formatterVersion && (
          <span className="badge badge-neutral" style={{ marginLeft: "8px" }}>formatter v{run.formatterVersion}</span>
        )}
      </summary>

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
          {systemParts.phase1 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">Phase 1 — Research (system)</p>
              <pre style={preStyle}>{systemParts.phase1}</pre>
            </div>
          )}

          {userParts.phase1 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">Phase 1 — Research (user context)</p>
              <pre style={preStyle}>{userParts.phase1}</pre>
            </div>
          )}

          {systemParts.phase2 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">Phase 2 — Formatter (system)</p>
              <pre style={preStyle}>{systemParts.phase2}</pre>
            </div>
          )}

          {userParts.phase2 && (
            <div style={{ marginTop: "16px" }}>
              <p className="label">Phase 2 — Formatter (user context)</p>
              <pre style={preStyle}>{userParts.phase2}</pre>
            </div>
          )}

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

      <div style={{ marginTop: "16px" }}>
        <p className="label">Raw Model Output</p>
        <pre style={{ ...preStyle, maxHeight: "400px" }}>
          {run.rawModelOutput || "Not recorded"}
        </pre>
      </div>
    </details>
  );
}
