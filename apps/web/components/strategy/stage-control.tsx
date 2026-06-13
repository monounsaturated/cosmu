"use client";

// module: StageControl — the v18 strat-sheet top bar: a lifecycle STAGE badge on the left and the
// matching Stop/Start affordance on the right. The stage is DERIVED honestly upstream from the real
// detail response (see deriveStage in the page) — backtest / paper / live / killed / queued — never
// fabricated. The action mirrors the stage:
//   • paper / live   → "Stop" (opens a plain-language confirm; honest about whether real money moves)
//   • backtest (gate passed) → "Start paper" (promote candidate)
//   • otherwise       → no action (queued / killed have nothing to start or stop)
//
// This is a presentational control: it surfaces the affordance and an honest confirm dialog. The actual
// mutation wiring (POST to the engine) is intentionally left to the existing live/launch path — the
// Stop/Start here calls the optional onStop/onStart the page passes, and degrades to a disabled, clearly
// labelled "engine action — wire to backend" state when none is provided, so we never pretend an action
// happened that did not.

import { useState, type ReactNode } from "react";
import { CircleStop, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type Stage = "queued" | "backtest" | "paper" | "live" | "killed";

const STAGE_META: Record<Stage, { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "border-border bg-surface-2/60 text-quiet" },
  backtest: { label: "Backtest", tone: "border-info/35 bg-info/[0.09] text-info" },
  paper: { label: "Paper", tone: "border-iris/35 bg-iris/[0.10] text-iris-soft" },
  live: { label: "Live", tone: "border-up/35 bg-up/[0.10] text-up" },
  killed: { label: "Killed", tone: "border-down/35 bg-down/[0.09] text-down" }
};

function StageBadge({ stage, ageDays }: { stage: Stage; ageDays: number | null }) {
  const meta = STAGE_META[stage];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.06em]",
        meta.tone
      )}
    >
      {stage === "live" ? <span className="size-1.5 rounded-full bg-up" aria-hidden /> : null}
      {meta.label}
      {ageDays !== null && ageDays > 0 ? <span className="font-medium tabular opacity-80">· {ageDays}d</span> : null}
    </span>
  );
}

// Honest confirm dialog. Plain language, no fabricated dollar figure unless the caller passes one.
function ConfirmStop({
  stage,
  strategyName,
  onConfirm,
  onCancel
}: {
  stage: Stage;
  strategyName: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const live = stage === "live";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-background/70 backdrop-blur-sm" onClick={onCancel} aria-hidden />
      <div className="card-grad relative z-10 w-full max-w-md space-y-4 rounded-lg border border-border/70 p-5 shadow-card">
        <h2 className={cn("text-base font-semibold tracking-tight", live ? "text-down" : "text-foreground")}>
          {live ? "Stop live trading" : "Stop paper track"}
        </h2>
        <p className="text-[13px] leading-relaxed text-muted">
          {live ? (
            <>
              Sell every open position for <strong className="text-foreground">{strategyName}</strong> to cash, kill the
              running bot, and place no further orders. <strong className="text-down">Real money moves.</strong> The P&amp;L
              it produced stays on the live record.
            </>
          ) : (
            <>
              Halt the paper track for <strong className="text-foreground">{strategyName}</strong> and close its simulated
              positions. <strong className="text-foreground">No real money is involved</strong> — this only stops the
              simulation. Its stats are kept so you can still review what happened.
            </>
          )}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant={live ? "primary" : "secondary"} size="sm" onClick={onConfirm} className={live ? "bg-down hover:bg-down" : undefined}>
            {live ? "Stop & sell" : "Stop track"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function StageControl({
  stage,
  ageDays,
  strategyName,
  gatePassed,
  onStop,
  onStart,
  extraAction
}: {
  stage: Stage;
  ageDays: number | null;
  strategyName: string;
  gatePassed: boolean;
  // Optional mutation callbacks — when absent the affordance renders disabled + honestly labelled.
  onStop?: () => void;
  onStart?: () => void;
  // The caller can inject the real launch-live button (e.g. for a gate-passed paper track).
  extraAction?: ReactNode;
}) {
  const [confirming, setConfirming] = useState(false);
  const canStop = stage === "paper" || stage === "live";
  const canStart = stage === "backtest" && gatePassed;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <StageBadge stage={stage} ageDays={ageDays} />
      <div className="flex items-center gap-2">
        {extraAction}
        {canStop ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirming(true)}
            className={stage === "live" ? "border-down/40 text-down hover:bg-down/[0.08]" : undefined}
          >
            <CircleStop className="size-4" /> Stop
          </Button>
        ) : null}
        {canStart ? (
          <Button variant="primary" size="sm" onClick={onStart} disabled={!onStart} title={!onStart ? "Engine action — wire to backend" : undefined}>
            <Play className="size-4" /> Start paper
          </Button>
        ) : null}
      </div>
      {confirming ? (
        <ConfirmStop
          stage={stage}
          strategyName={strategyName}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            onStop?.();
          }}
        />
      ) : null}
    </div>
  );
}
