"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Play, Square } from "lucide-react";
import { EditBotModal } from "./edit-bot-modal";
import { ModalShell } from "./modal-shell";

type BotControlsProps = {
  botId: string;
  isActive: boolean;
};

export function BotControls({ botId, isActive: initialIsActive }: BotControlsProps) {
  const router = useRouter();
  const [isActive, setIsActive] = useState(initialIsActive);
  const [loading, setLoading] = useState<"kill" | "run" | null>(null);
  const [confirmKillOpen, setConfirmKillOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
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
      setFeedback({
        type: "success",
        text: data.runId ? `Agent stopped (${data.runId.slice(0, 8)})` : "Agent stopped"
      });
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
      const idSuffix = data.runId ? ` (${data.runId.slice(0, 8)})` : "";
      setFeedback({ type: "success", text: `Run ${data.status}${idSuffix}` });
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
          className="btn btn-secondary btn-icon-action btn-icon-edit"
          onClick={() => setEditOpen(true)}
          disabled={loading !== null}
          aria-label="Edit agent"
          title="Edit agent"
        >
          <Pencil size={15} />
          <span className="sr-only">Edit</span>
        </button>
        <button
          className="btn btn-warn btn-icon-action btn-icon-stop"
          onClick={() => setConfirmKillOpen(true)}
          disabled={!isActive || loading !== null}
          aria-label={loading === "kill" ? "Stopping agent" : "Stop agent"}
          title={loading === "kill" ? "Stopping agent" : "Stop agent"}
        >
          <Square size={15} />
          <span className="sr-only">{loading === "kill" ? "Stopping" : "Stop"}</span>
        </button>
        <button
          className="btn btn-primary btn-icon-action btn-icon-run"
          onClick={triggerRun}
          disabled={!isActive || loading !== null}
          aria-label={loading === "run" ? "Running agent" : "Run agent"}
          title={loading === "run" ? "Running agent" : "Run agent"}
        >
          <Play size={15} />
          <span className="sr-only">{loading === "run" ? "Running" : "Run"}</span>
        </button>
      </div>
      {feedback && (
        <p className={`feedback feedback-${feedback.type}`}>{feedback.text}</p>
      )}
      {confirmKillOpen && (
        <ModalShell
          title="Stop agent?"
          description="This will cancel open orders, sell all current positions, and permanently stop the agent."
          onClose={() => setConfirmKillOpen(false)}
        >
          <p className="muted modal-warning-copy">
            This cannot be restarted. Use this only when the strategy should leave the market now.
          </p>
          <div className="form-actions">
            <button className="btn" type="button" onClick={() => setConfirmKillOpen(false)} disabled={loading !== null}>
              Cancel
            </button>
            <button className="btn btn-warn" type="button" onClick={kill} disabled={loading !== null}>
              {loading === "kill" ? "Stopping..." : "Yes, stop agent"}
            </button>
          </div>
        </ModalShell>
      )}
      {editOpen && (
        <EditBotModal
          botId={botId}
          onClose={() => setEditOpen(false)}
          onSuccess={() => {
            setEditOpen(false);
            router.refresh();
          }}
        />
      )}
    </div>
  );
}
