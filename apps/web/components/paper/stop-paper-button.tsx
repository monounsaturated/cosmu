"use client";

// The Paper "Stop" control (Iris Bento). A grey `.btn.btn-sm` in the Paper toolbar that opens the confirm
// Modal from the mockup (lines 1202-1211): halting every running paper strategy closes their SIMULATED
// positions and frees their virtual capital — NO real money is involved, each keeps its stats, and live
// trading is untouched.
//
// The confirm sends POST /paper/stop through the same-origin engine proxy (engineFetch) with the two-click
// safety pattern used across the surface: a per-control in-flight flag (always cleared in `finally`) and an
// 8s AbortController so a hung engine can never leave the button stuck. Offline / rejected → an honest note,
// never a silent success. router.refresh() re-pulls the real server data after a successful stop.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Modal } from "@/components/ui/modal";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

export function StopPaperButton() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function stopAll() {
    if (pending) return;
    setNote(null);
    if (!ENGINE_CONFIGURED) {
      setNote("Engine not connected — set API_BASE_URL. Paper strategies can only be stopped against a connected engine.");
      return;
    }
    setPending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await engineFetch("/paper/stop", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ scope: "all", confirm: true }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine rejected the stop");
      setOpen(false);
      router.refresh();
    } catch {
      setNote("Couldn’t stop the paper strategies — the engine didn’t accept the request. Try again.");
    } finally {
      clearTimeout(timer);
      setPending(false);
    }
  }

  return (
    <>
      <button className="btn btn-sm" onClick={() => setOpen(true)}>
        Stop
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Stop all paper strategies"
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-iris" onClick={stopAll} disabled={pending}>
              Stop paper strategies
            </button>
          </>
        }
      >
        Halt every running paper strategy and close their simulated positions. <strong>No real money is
        involved</strong> — this only stops the simulations and frees their virtual capital. Each one{" "}
        <strong>keeps its stats</strong> so you can still review what happened. Live trading is not affected.
        {note ? (
          <div style={{ marginTop: 12, color: "var(--down)", fontSize: 12 }}>{note}</div>
        ) : null}
      </Modal>
    </>
  );
}
