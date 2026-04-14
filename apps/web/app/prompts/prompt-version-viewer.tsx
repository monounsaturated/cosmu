"use client";

import { useState } from "react";
import { LocalTime } from "../local-time";

interface Props {
  promptId: string;
  versionId: string;
  versionNumber: number;
  createdAt: string;
}

export function PromptVersionViewer({ promptId, versionId, versionNumber, createdAt }: Props) {
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const loadBody = async () => {
    if (body !== null) {
      setExpanded(!expanded);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`/api/prompts/${promptId}/versions/${versionId}`);
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      setBody(data.body ?? "No body available");
      setExpanded(true);
    } catch {
      setBody("Failed to load prompt body.");
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ border: "1px solid #27272a", borderRadius: "8px", overflow: "hidden" }}>
      <button
        onClick={loadBody}
        disabled={loading}
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 16px",
          background: expanded ? "#1c1c1f" : "#18181b",
          border: "none",
          color: "#e4e4e7",
          cursor: "pointer",
          fontFamily: "inherit",
          fontSize: "13px",
          transition: "background 0.15s",
          textAlign: "left",
        }}
      >
        <span>
          <span style={{ fontWeight: 600, marginRight: "8px" }}>v{versionNumber}</span>
          <span className="muted"><LocalTime value={createdAt} /></span>
        </span>
        <span style={{ color: "#71717a", fontSize: "12px" }}>
          {loading ? "Loading…" : expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && body !== null && (
        <div className="run-detail-pre" style={{ borderRadius: 0, borderTop: "1px solid #27272a", maxHeight: "500px" }}>
          {body}
        </div>
      )}
    </div>
  );
}
