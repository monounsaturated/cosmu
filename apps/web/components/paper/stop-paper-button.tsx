"use client";

// The Paper "Stop" control (Iris Bento) — a grey `.btn.btn-sm` in the Paper toolbar that opens the v18
// confirm Modal (mockup lines 1202-1211). Paper tracks are managed AUTOMATICALLY by the Gate (they enter
// paper on Gate-pass and leave on decay/kill — "you don't move them manually"), and the engine exposes no
// manual paper-stop route yet. So this is an HONEST, not-yet-wired affordance, exactly like the sheet's
// StageControl Stop: it surfaces the action + a plain-language dialog, and on confirm it says plainly that
// nothing was changed rather than calling a route that doesn't exist or pretending a stop happened. Wire it
// to a real POST when the engine ships a paper-stop endpoint.

import { useState } from "react";
import { Modal } from "@/components/ui/modal";

export function StopPaperButton() {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  return (
    <>
      <button
        className="btn btn-sm"
        onClick={() => {
          setNote(null);
          setOpen(true);
        }}
      >
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
            <button
              className="btn btn-iris"
              onClick={() =>
                setNote(
                  "Paper tracks are managed automatically by the Gate — there is no manual paper-stop yet, so nothing was changed."
                )
              }
            >
              Stop paper strategies
            </button>
          </>
        }
      >
        Halt every running paper strategy and close their simulated positions. <strong>No real money is
        involved</strong> — this only stops the simulations and frees their virtual capital. Each one{" "}
        <strong>keeps its stats</strong> so you can still review what happened. Live trading is not affected.
        {note ? <div style={{ marginTop: 12, color: "var(--down)", fontSize: 12 }}>{note}</div> : null}
      </Modal>
    </>
  );
}
