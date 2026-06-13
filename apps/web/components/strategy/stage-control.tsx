"use client";

// module: StageControl — the v18 strat-sheet top bar (Iris Bento `.psec.panel-top`): a lifecycle
// `.stage-badge` on the left and the matching action on the right. The stage is DERIVED honestly upstream
// from the real detail response (see deriveStage in the page) — backtest / paper / live / killed / queued —
// never fabricated. The action mirrors the stage:
//   • paper / live → "Stop" (opens an honest confirm; plain about whether real money moves)
//   • otherwise    → no action. Promotion to paper/live is NOT a manual UI action — the Gate auto-promotes
//     survivors, and live is launched via the CLI (Commands · `cosmu live launch`).
//
// The Stop confirm is presentational + honest: it surfaces the affordance and a plain-language dialog. When
// no real mutation path is wired it stays a clearly-labelled affordance, so we never pretend an action
// happened that did not.

import { useState } from "react";
import { Modal } from "@/components/ui/modal";

export type Stage = "queued" | "backtest" | "paper" | "live" | "killed";

const STAGE_BADGE_CLASS: Record<Stage, string> = {
  queued: "stage-badge sb-queued",
  backtest: "stage-badge sb-backtest-stage",
  paper: "stage-badge sb-paper",
  live: "stage-badge sb-live",
  killed: "stage-badge sb-killed"
};
const STAGE_LABEL: Record<Stage, string> = {
  queued: "Queued",
  backtest: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};

export function StageControl({
  stage,
  ageDays,
  strategyName
}: {
  stage: Stage;
  ageDays: number | null;
  strategyName: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const canStop = stage === "paper" || stage === "live";
  const live = stage === "live";

  return (
    <div className="psec panel-top" style={{ margin: 0 }}>
      <div>
        <span className={STAGE_BADGE_CLASS[stage]} style={{ display: "inline-flex" }}>
          {STAGE_LABEL[stage]}
          {ageDays !== null && ageDays > 0 ? <span className="tab" style={{ opacity: 0.8 }}>· {ageDays}d</span> : null}
        </span>
      </div>
      <div className="panel-actions">
        {canStop ? (
          <button type="button" className="btn btn-danger btn-xs" onClick={() => setConfirming(true)}>
            Stop
          </button>
        ) : null}
      </div>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={live ? "Stop live trading" : "Stop paper track"}
        titleColor={live ? "var(--down)" : undefined}
        actions={
          <>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <button type="button" className={live ? "btn btn-danger btn-sm" : "btn btn-sm"} onClick={() => setConfirming(false)}>
              {live ? "Stop & sell" : "Stop track"}
            </button>
          </>
        }
      >
        {live ? (
          <p className="ai-body">
            Sell every open position for <strong style={{ color: "var(--fg)" }}>{strategyName}</strong> to cash, kill the
            running bot, and place no further orders. <strong className="dn">Real money moves.</strong> The P&amp;L it
            produced stays on the live record.
          </p>
        ) : (
          <p className="ai-body">
            Halt the paper track for <strong style={{ color: "var(--fg)" }}>{strategyName}</strong> and close its simulated
            positions. <strong style={{ color: "var(--fg)" }}>No real money is involved</strong> — this only stops the
            simulation. Its stats are kept so you can still review what happened.
          </p>
        )}
      </Modal>
    </div>
  );
}
