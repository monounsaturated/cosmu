"use client";

// module: PhasedEquity — the v18 strat-sheet centrepiece: ONE equity panel with a Backtest / Paper / Live
// phase selector. The mental model is the lifecycle read left-to-right — historical evidence (Backtest),
// forward proof on live data (Paper), real-capital record (Live). Each phase shows the RIGHT proof for
// that stage and nothing fabricated:
//   • Backtest → per-fold out-of-sample returns (FoldBars), the historical evidence.
//   • Paper    → the interactive equity curve built only from real fills (TvChart, mode="sim").
//   • Live     → the live equity curve when the track has one; otherwise an honest "not reached" panel.
//
// Phases the strategy has NOT reached are greyed and disabled in the selector (a tooltip says why), and
// selecting them is impossible — so the control itself communicates how far along the strategy is without
// ever faking a curve. The default phase is the furthest one reached.

import { useState } from "react";
import { Lock } from "lucide-react";
import type { Backtest, Point } from "@cosmu/contracts-ts";
import { TvChart } from "@/components/charts/tv-chart";
import { FoldBars } from "@/components/charts/fold-bars";
import { ChartEmpty } from "@/components/charts/chart-kit";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Phase = "backtest" | "paper" | "live";

const PHASE_LABEL: Record<Phase, string> = { backtest: "Backtest", paper: "Paper", live: "Live" };

export function PhasedEquity({
  backtests,
  paperCurve,
  liveCurve = [],
  height = 240
}: {
  backtests: Backtest[];
  // Forward (paper) equity curve, derived from real fills upstream. Empty = paper not yet meaningful.
  paperCurve: Point[];
  // Live equity curve when this track trades real capital. Empty = never went live.
  liveCurve?: Point[];
  height?: number;
}) {
  const reached: Record<Phase, boolean> = {
    backtest: backtests.length > 0,
    paper: paperCurve.length >= 2,
    live: liveCurve.length >= 2
  };
  const whyBlocked: Record<Phase, string> = {
    backtest: "Not backtested yet — no fold evidence.",
    paper: "No paper track yet — the forward curve renders once it has ≥ 2 fills on live data.",
    live: "Never went live — no real-capital record."
  };

  // Default to the furthest phase actually reached, so the panel opens on the most current proof.
  const initial: Phase = reached.live ? "live" : reached.paper ? "paper" : "backtest";
  const [phase, setPhase] = useState<Phase>(initial);

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
          Equity — {PHASE_LABEL[phase]}
          <Tooltip content="Backtest shows per-fold out-of-sample returns (historical evidence). Paper is the forward equity curve, built only from real fills. Live is the real-capital record. Phases not yet reached are greyed — never a fabricated curve." />
        </div>
        {/* Phase selector — reached phases are live buttons; unreached ones are locked + disabled. */}
        <div className="inline-flex overflow-hidden rounded-md border border-border/70">
          {(["backtest", "paper", "live"] as Phase[]).map((p, i) => {
            const ok = reached[p];
            const active = phase === p;
            return (
              <button
                key={p}
                type="button"
                disabled={!ok}
                onClick={() => ok && setPhase(p)}
                aria-pressed={active}
                title={ok ? undefined : whyBlocked[p]}
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-[0.06em] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/45",
                  i > 0 && "border-l border-border/70",
                  active
                    ? "bg-iris/12 text-iris-soft"
                    : ok
                      ? "text-muted hover:bg-surface-2/60 hover:text-foreground"
                      : "cursor-not-allowed text-quiet/55"
                )}
              >
                {!ok ? <Lock className="size-2.5" aria-hidden /> : null}
                {PHASE_LABEL[p]}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        {phase === "backtest" ? (
          reached.backtest ? (
            <FoldBars backtests={backtests} height={height} />
          ) : (
            <ChartEmpty title="No fold data" hint={whyBlocked.backtest} height={height} />
          )
        ) : phase === "paper" ? (
          reached.paper ? (
            <TvChart points={paperCurve} mode="sim" height={height} valueKind="usd" />
          ) : (
            <ChartEmpty title="No paper track yet" hint={whyBlocked.paper} height={height} />
          )
        ) : reached.live ? (
          <TvChart points={liveCurve} mode="live" height={height} valueKind="usd" />
        ) : (
          <ChartEmpty title="Never went live" hint={whyBlocked.live} height={height} />
        )}
      </div>
    </div>
  );
}
