"use client";

import { useState } from "react";
import { Loader2, OctagonX, X } from "lucide-react";
import { useRouter } from "next/navigation";

type KillAllBotsButtonProps = {
  activeBotCount: number;
  disabled?: boolean;
};

export function KillAllBotsButton({ activeBotCount, disabled = false }: KillAllBotsButtonProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trigger = async () => {
    if (busy || disabled || activeBotCount === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/bots/kill-all", { method: "POST" });
      if (res.ok) {
        setConfirmOpen(false);
        router.refresh();
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? res.statusText);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="btn panic-button"
        onClick={() => {
          setError(null);
          setConfirmOpen(true);
        }}
        disabled={busy || disabled || activeBotCount === 0}
        title={activeBotCount === 0 ? "No active agents to stop" : "Stop every active agent immediately"}
      >
        <OctagonX size={16} />
        {activeBotCount === 0 ? "All stopped" : "Stop all"}
      </button>

      {confirmOpen && (
        <div className="modal-overlay" role="presentation">
          <section className="modal-content panic-modal" role="dialog" aria-modal="true" aria-labelledby="panic-modal-title">
            <header className="modal-header">
              <div className="modal-title-block">
                <h2 id="panic-modal-title">Stop all active agents</h2>
                <p>
                  This disables {activeBotCount} active agent{activeBotCount === 1 ? "" : "s"} first, then attempts
                  best-effort liquidation without making model calls.
                </p>
              </div>
              <button className="modal-close" type="button" onClick={() => setConfirmOpen(false)} aria-label="Close">
                <X size={18} />
              </button>
            </header>

            <div className="modal-form">
              <div className="panic-confirm-panel">
                <strong>Cost guard</strong>
                <p>
                  This cuts off scheduled LLM runs immediately. The backend disables every active agent before doing any
                  slower cleanup work.
                </p>
              </div>

              {error && <p className="form-error">{error}</p>}

              <div className="form-actions">
                <button className="btn btn-secondary" type="button" onClick={() => setConfirmOpen(false)} disabled={busy}>
                  Cancel
                </button>
                <button className="btn panic-button panic-button-solid" type="button" onClick={trigger} disabled={busy}>
                  {busy ? <Loader2 size={16} className="spin-icon" /> : <OctagonX size={16} />}
                  Stop all agents
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
