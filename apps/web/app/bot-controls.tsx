"use client";

import { useState } from "react";

type BotControlsProps = {
  botId: string;
  enabled: boolean;
};

export function BotControls({ botId, enabled: initialEnabled }: BotControlsProps) {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [loading, setLoading] = useState<"toggle" | "run" | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const clearFeedback = () => setTimeout(() => setFeedback(null), 4000);

  const toggle = async () => {
    setLoading("toggle");
    setFeedback(null);
    try {
      const res = await fetch(`/api/bots/${botId}/toggle`, { method: "PATCH" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Toggle failed");
      setEnabled(data.enabled);
      setFeedback({ type: "success", text: data.enabled ? "Bot enabled" : "Bot disabled" });
    } catch (e) {
      setFeedback({ type: "error", text: e instanceof Error ? e.message : "Toggle failed" });
    } finally {
      setLoading(null);
      clearFeedback();
    }
  };

  const triggerRun = async () => {
    setLoading("run");
    setFeedback(null);
    try {
      const res = await fetch(`/api/bots/${botId}/run`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Run failed");
      setFeedback({ type: "success", text: `Run ${data.status} (${data.runId.slice(0, 8)})` });
    } catch (e) {
      setFeedback({ type: "error", text: e instanceof Error ? e.message : "Run failed" });
    } finally {
      setLoading(null);
      clearFeedback();
    }
  };

  return (
    <div className="bot-controls">
      <div className="bot-controls-buttons">
        <button
          className={`btn ${enabled ? "btn-warn" : "btn-primary"}`}
          onClick={toggle}
          disabled={loading !== null}
        >
          {loading === "toggle" ? "..." : enabled ? "Disable" : "Enable"}
        </button>
        <button
          className="btn btn-primary"
          onClick={triggerRun}
          disabled={!enabled || loading !== null}
        >
          {loading === "run" ? "Running..." : "Run Now"}
        </button>
      </div>
      {feedback && (
        <p className={`feedback feedback-${feedback.type}`}>{feedback.text}</p>
      )}
    </div>
  );
}
