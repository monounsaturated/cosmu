"use client";

// module: StageControl — the v18 strat-sheet top bar (Iris Bento `.psec.panel-top`): a lifecycle
// `.stage-badge` on the left and the matching action on the right. The stage is DERIVED honestly upstream
// from the real detail response (see deriveStage in the page) — backtest / paper / live / killed / queued —
// never fabricated. The affordances mirror the stage:
//   • live CANDIDATE (paper-stage, or a gate-passed backtest) → a small red "Go Live" button next to the
//     badge opens the GoLiveModal, which POSTs /live/launch (the SAME endpoint the CLI used). Arming only
//     RECORDS INTENT — the engine enforces the real eligibility gate (paper maturity + regime + caps +
//     global toggle + kill-switch) and runs testnet first; live ORDER execution is intentionally not wired.
//   • paper / live → "Stop" on the right (opens an honest confirm; plain about whether real money moves).
//     Promotion INTO paper is not a manual action — the Gate auto-promotes survivors.
//
// Both controls are honest: Go Live surfaces the engine's verdict verbatim (armed OR refusal reason) and the
// Stop confirm is a plain-language dialog. Neither fires an order from this sheet, so we never pretend an
// action happened that did not.

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { GoLiveModal } from "./go-live-modal";
import { type Stage, STAGE_LABEL, STAGE_BADGE_CLASS } from "@/lib/lifecycle";

// Re-export so existing `import type { Stage } from "./stage-control"` consumers (strategy-sheet, ai-summary,
// equity-panel) keep working — the canonical definition + maps live in the shared lib/lifecycle module.
export type { Stage };

export function StageControl({
  stage,
  ageDays,
  strategyName,
  versionId,
  defaultSymbol,
  goLiveEligible
}: {
  stage: Stage;
  ageDays: number | null;
  strategyName: string;
  // Needed to arm this exact Version live via the Go Live modal (POST /live/launch).
  versionId?: string;
  defaultSymbol?: string | null;
  // Whether to show the "Go Live" affordance: a live CANDIDATE (paper-stage, or a gate-passed backtest). The
  // engine's /live/launch enforces the REAL eligibility gate (paper maturity + regime) and refuses honestly —
  // this just surfaces the entry point so the operator can see + drive the flow.
  goLiveEligible?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [goLive, setGoLive] = useState(false);
  const canStop = stage === "paper" || stage === "live";
  const live = stage === "live";
  // Red "Go Live" sits next to the stage badge for a live candidate we can attempt to arm (not already live).
  const canGoLive = Boolean(goLiveEligible) && stage !== "live" && stage !== "killed" && Boolean(versionId);

  return (
    <div className="psec panel-top" style={{ margin: 0 }}>
      <div style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        <span className={STAGE_BADGE_CLASS[stage]} style={{ display: "inline-flex" }}>
          {STAGE_LABEL[stage]}
          {ageDays !== null && ageDays > 0 ? <span className="tab" style={{ opacity: 0.8 }}>· {ageDays}d</span> : null}
        </span>
        {canGoLive ? (
          <button type="button" className="btn btn-danger btn-xs" onClick={() => setGoLive(true)} data-tip="Arm this strategy for live trading (Binance spot). Real orders stay behind the toggle, caps + kill-switch.">
            Go Live
          </button>
        ) : null}
      </div>
      <div className="panel-actions">
        {canStop ? (
          <button type="button" className={live ? "btn btn-danger btn-xs" : "btn btn-xs"} onClick={() => setConfirming(true)}>
            Stop
          </button>
        ) : null}
      </div>

      {canGoLive && versionId ? (
        <GoLiveModal
          open={goLive}
          onClose={() => setGoLive(false)}
          versionId={versionId}
          strategyName={strategyName}
          defaultSymbol={defaultSymbol}
        />
      ) : null}

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={live ? "Stopping a live strategy" : "Stopping a paper track"}
        titleColor={live ? "var(--down)" : undefined}
        actions={
          <button type="button" className="btn btn-sm" onClick={() => setConfirming(false)}>
            Close
          </button>
        }
      >
        {live ? (
          <p className="ai-body">
            To stop <strong style={{ color: "var(--fg)" }}>{strategyName}</strong> live, go to the{" "}
            <strong style={{ color: "var(--fg)" }}>Live</strong> page and press the{" "}
            <strong className="dn">Stop</strong> button in the top-right — that is the one path that moves{" "}
            <strong className="dn">real money</strong>, with the hard caps applied. This sheet shows the stage; it
            never fires orders itself, so there&apos;s no one-click sell here by design.
          </p>
        ) : (
          <p className="ai-body">
            Paper tracks are managed by the <strong style={{ color: "var(--fg)" }}>Gate</strong>, not stopped by hand
            here — <strong style={{ color: "var(--fg)" }}>{strategyName}</strong> leaves Paper when the FDR gate kills
            it or you launch it Live, and its stats are kept either way. No real money is involved in Paper.
          </p>
        )}
      </Modal>
    </div>
  );
}
