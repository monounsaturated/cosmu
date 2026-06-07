// module: MoneyHero — the Overview's ONE hero figure. Answers the first half of "is the machine making
// money, and does it need me?" in a single glance: the live SIMULATION net P&L (net of fees) across every
// funded track, drawn large with the REAL /overview equity curve behind it.
//
// HONESTY CONTRACT (the machine that never lies): every number here is real engine data. With no engine we
// show "—" and "engine offline"; with the engine up but no funded tracks yet we show an honest "$0 · no
// funded tracks yet" day-0 state and render NO curve (the Sparkline already declines to draw <2 points —
// never a flat fake line). The figure is explicitly labelled "Simulation" so a sim curve is never mistaken
// for live money. Net of fees is stated, because that is the only number that matters.

import Link from "next/link";
import { ArrowRight, Pause, Play, TrendingUp } from "lucide-react";
import type { OverviewResponse } from "@cosmu/contracts-ts";
import type { AutonomyStatus } from "@/app/autonomy-contracts";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/viz";
import { cn, formatUsd, timeAgo } from "@/lib/utils";

export function MoneyHero({
  overview,
  overviewConnected,
  status,
  statusConnected
}: {
  overview: OverviewResponse;
  overviewConnected: boolean;
  status: AutonomyStatus;
  statusConnected: boolean;
}) {
  const curve = overview.equity_curve ?? [];
  const equityValues = curve.map((p) => p.value);
  const hasCurve = equityValues.length >= 2;
  const pnl = overview.pnl_net;

  // Machine state chip — running / paused / idle, plus the live-vs-sim mode. Honest "unknown" offline.
  const running = statusConnected && status.running && !status.paused;
  const stateLabel = !statusConnected ? "Unknown" : status.paused ? "Paused" : status.running ? "Running" : "Idle";
  const stateVariant = running ? "up" : status.paused ? "warn" : "muted";
  const modeLabel = status.live_enabled ? "Live" : "Simulation";
  const lastTick = timeAgo(status.last_tick_at);

  const tone: "up" | "down" | "muted" = !overviewConnected ? "muted" : pnl > 0 ? "up" : pnl < 0 ? "down" : "muted";
  const valueColor = !overviewConnected ? "text-quiet" : pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "text-foreground";

  // The honest sub-line under the figure — what the number means, and the day-0 state when there is no curve.
  const subline = !overviewConnected
    ? "Engine offline — no live figure to show."
    : hasCurve
      ? "Net of fees, across every funded simulation track."
      : "No funded tracks yet — the figure starts moving when a strategy clears the Gate.";

  return (
    <Card className="relative overflow-hidden">
      {/* A whisper-thin accent rail keyed to the sign of the money — green up, red down, neutral at zero. */}
      <span
        className={cn(
          "absolute inset-y-0 left-0 w-0.5",
          tone === "up" ? "bg-up" : tone === "down" ? "bg-down" : "bg-border-strong"
        )}
        aria-hidden
      />
      <div className="flex flex-col gap-5 p-5 sm:p-6 lg:flex-row lg:items-center lg:justify-between">
        {/* The money. */}
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <TrendingUp className="size-4 text-iris-soft" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-quiet">
              Simulation net P&amp;L
            </span>
            <Badge variant={stateVariant} className="ml-1">
              {running ? <Play className="size-3" /> : status.paused ? <Pause className="size-3" /> : null}
              {stateLabel}
            </Badge>
            <Badge variant={status.live_enabled ? "info" : "muted"}>{modeLabel}</Badge>
          </div>
          <div className={cn("mt-2 text-[40px] font-semibold leading-none tracking-tight tabular sm:text-[52px]", valueColor)}>
            {overviewConnected ? formatUsd(pnl) : "—"}
          </div>
          <p className="mt-2.5 max-w-md text-[12.5px] leading-relaxed text-muted">{subline}</p>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-quiet">
            {statusConnected && lastTick ? (
              <span>
                Last cycle {lastTick} · {status.cycles_run} run
              </span>
            ) : (
              <span>Machine status unknown — the Gate ledger below is read from disk.</span>
            )}
          </div>
        </div>

        {/* The ONE chart — the real equity curve at hero scale. Renders nothing on day 0 (honest). */}
        <div className="flex shrink-0 flex-col items-stretch gap-3 lg:w-[340px]">
          {hasCurve ? (
            <Sparkline
              values={equityValues}
              width={340}
              height={96}
              strokeWidth={2}
              ariaLabel="simulation equity curve, net of fees"
              className="w-full"
            />
          ) : (
            <div className="flex h-[96px] items-center justify-center rounded-md border border-dashed border-border/60 bg-surface-2/20 text-[11.5px] text-quiet">
              {overviewConnected ? "Equity curve appears once a track is funded" : "Engine offline"}
            </div>
          )}
          <Link
            href="/console"
            className={cn(
              "inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-iris/40 bg-iris/12 px-4 text-[12.5px] font-medium text-iris-soft",
              "transition-colors hover:border-iris/60 hover:bg-iris/20",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            )}
          >
            Open Console <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </div>
    </Card>
  );
}
