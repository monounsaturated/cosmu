"use client";

import { useState } from "react";

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
  rawModelOutput: string | null;
  parsedDecision: Record<string, unknown> | null;
  validationResult: Record<string, unknown> | null;
};

export function RecentRunsTable({ runs }: { runs: RunRow[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const toggleExpand = async (runId: string) => {
    if (expandedId === runId) {
      setExpandedId(null);
      setDetail(null);
      return;
    }

    setExpandedId(runId);
    setDetail(null);
    setLoading(true);

    try {
      const res = await fetch(`/api/runs/${runId}`);
      if (res.ok) {
        setDetail(await res.json());
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

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
          <>
            <tr
              key={run.id}
              className={`run-row ${expandedId === run.id ? "run-row-expanded" : ""}`}
              onClick={() => toggleExpand(run.id)}
              style={{ cursor: "pointer" }}
            >
              <td>{run.botName}</td>
              <td><span className={`badge badge-${run.status}`}>{run.status}</span></td>
              <td>{new Date(run.startedAt).toLocaleString()}</td>
              <td>{run.decisionMode ?? "-"}</td>
              <td className="run-summary-cell">{run.rationaleSummary ?? "-"}</td>
              <td className="run-expand-icon">{expandedId === run.id ? "▾" : "▸"}</td>
            </tr>
            {expandedId === run.id && (
              <tr key={`${run.id}-detail`} className="run-detail-row">
                <td colSpan={6}>
                  {loading ? (
                    <p className="muted">Loading run details…</p>
                  ) : detail ? (
                    <div className="run-detail-panels">
                      <div className="run-detail-panel">
                        <h4>System Prompt (sent to LLM)</h4>
                        <pre className="run-detail-pre">
                          {detail.promptSystem ?? "Not stored (run predates this feature)"}
                        </pre>
                      </div>
                      <div className="run-detail-panel">
                        <h4>User Message (data injected)</h4>
                        <pre className="run-detail-pre">
                          {detail.promptUser ?? "Not stored (run predates this feature)"}
                        </pre>
                      </div>
                      <div className="run-detail-panel">
                        <h4>LLM Response (raw)</h4>
                        <pre className="run-detail-pre">
                          {detail.rawModelOutput
                            ? tryFormatJson(detail.rawModelOutput)
                            : "No response recorded"}
                        </pre>
                      </div>
                      {detail.validationResult && (
                        <div className="run-detail-panel">
                          <h4>Validation Result</h4>
                          <pre className="run-detail-pre">
                            {JSON.stringify(detail.validationResult, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="muted">Could not load details.</p>
                  )}
                </td>
              </tr>
            )}
          </>
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
