"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type BotControlsProps = {
  botId: string;
  isActive: boolean;
};

export function BotControls({ botId, isActive: initialIsActive }: BotControlsProps) {
  const router = useRouter();
  const [isActive, setIsActive] = useState(initialIsActive);
  const [loading, setLoading] = useState<"kill" | "run" | null>(null);
  const [confirmKillOpen, setConfirmKillOpen] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    setIsActive(initialIsActive);
  }, [initialIsActive]);

  const clearFeedback = () => setTimeout(() => setFeedback(null), 4000);

  const kill = async () => {
    // Close modal immediately so the user gets instant feedback
    setConfirmKillOpen(false);
    setLoading("kill");
    setFeedback(null);
    try {
      const res = await fetch(`/api/bots/${botId}/kill`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Kill failed");
      setIsActive(false);
      setFeedback({ type: "success", text: `Bot killed (${data.runId.slice(0, 8)})` });
      router.refresh();
    } catch (e) {
      setFeedback({ type: "error", text: e instanceof Error ? e.message : "Kill failed" });
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
      router.refresh();
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
          className="btn btn-warn"
          onClick={() => setConfirmKillOpen(true)}
          disabled={!isActive || loading !== null}
        >
          {loading === "kill" ? "Killing..." : "Kill Bot"}
        </button>
        <button
          className="btn btn-primary"
          onClick={triggerRun}
          disabled={!isActive || loading !== null}
        >
          {loading === "run" ? "Running..." : "Run Now"}
        </button>
      </div>
      {!isActive && (
        <p className="muted" style={{ marginTop: "8px", fontSize: "12px" }}>
          Bot killed. Duplicate this bot to restart with a fresh allocation.
        </p>
      )}
      {feedback && (
        <p className={`feedback feedback-${feedback.type}`}>{feedback.text}</p>
      )}
      {confirmKillOpen && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: "460px" }}>
            <div className="modal-header">
              <h2>Kill Bot?</h2>
              <button className="modal-close" onClick={() => setConfirmKillOpen(false)}>✕</button>
            </div>
            <p className="muted" style={{ marginBottom: "16px", lineHeight: 1.5 }}>
              This will cancel open orders, sell all current positions, and permanently stop the bot.
              It cannot be restarted.
            </p>
            <div className="form-actions">
              <button className="btn" onClick={() => setConfirmKillOpen(false)} disabled={loading !== null}>
                Cancel
              </button>
              <button className="btn btn-warn" onClick={kill} disabled={loading !== null}>
                {loading === "kill" ? "Killing..." : "Yes, kill bot"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
