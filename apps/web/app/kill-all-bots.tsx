"use client";

import { useState } from "react";

export function KillAllBotsButton() {
  const [busy, setBusy] = useState(false);

  const trigger = async () => {
    if (busy) return;
    if (!window.confirm("Kill all bots and liquidate their positions? This cannot be undone.")) return;
    setBusy(true);
    try {
      const res = await fetch("/api/bots/kill-all", { method: "POST" });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        window.alert(`Kill all complete — ${data.killed ?? 0} bot(s) liquidated.`);
        window.location.reload();
      } else {
        const data = await res.json().catch(() => ({}));
        window.alert(`Kill all failed: ${data.error ?? res.statusText}`);
      }
    } catch (error) {
      window.alert(`Kill all failed: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={trigger}
      disabled={busy}
      style={{
        background: "#7f1d1d",
        color: "#fca5a5",
        border: "1px solid #dc2626",
        borderRadius: "6px",
        padding: "6px 14px",
        fontSize: "12px",
        fontWeight: 600,
        cursor: busy ? "wait" : "pointer",
        opacity: busy ? 0.6 : 1
      }}
    >
      {busy ? "Killing all bots…" : "Kill All Bots"}
    </button>
  );
}
