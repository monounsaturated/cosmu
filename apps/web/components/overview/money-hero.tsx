// module: MoneyHero — the Overview's ONE hero figure. Answers the first half of "is the machine making
// money, and does it need me?" in a single glance: the live SIMULATION net P&L (net of fees) across every
// funded track, drawn large with the REAL /overview equity curve behind it.
//
// HONESTY CONTRACT (the machine that never lies): every number here is real engine data. With no engine we
// show "—" and "engine offline"; with the engine up but no funded tracks yet we show an honest "$0 · no
// funded tracks yet" day-0 state and render NO curve (the Sparkline already declines to draw <2 points —
// never a flat fake line). The figure is explicitly labelled "Paper" so a sim curve is never mistaken
// for live money. Net of fees is stated, because that is the only number that matters.

import Link from "next/link";
import { ArrowRight, Pause, Play } from "lucide-react";
import type { AutonomyStatusResponse, OverviewResponse } from "@cosmu/contracts-ts";
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
  status: AutonomyStatusResponse;
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
  const modeLabel = status.live_enabled ? "Live" : "Paper";
  const lastTick = timeAgo(status.last_tick_at);

  const tone: "up" | "down" | "muted" = !overviewConnected ? "muted" : pnl > 0 ? "up" : pnl < 0 ? "down" : "muted";
  const valueColor = !overviewConnected ? "text-quiet" : pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "text-foreground";

  // The honest sub-line under the figure — what the number means, and the day-0 state when there is no curve.
  const subline = !overviewConnected
    ? "Engine offline — no live figure to show."
    : hasCurve
      ? "Net of fees, across every funded paper track."
      : "No funded tracks yet — the figure starts moving when a strategy clears the Gate.";

  // Operating-cost-vs-alpha ratio — a real /overview field. Honest: 0 reads as "—" (not yet measurable),
  // never a fabricated efficiency. Green when the machine spends little to earn, red when it's underwater.
  const opex = overview.opex_vs_alpha;
  const opexLabel = !overviewConnected || opex === 0 ? "—" : `${(opex * 100).toFixed(1)}%`;
  const opexTone = opex === 0 ? "text-muted" : opex <= 0.1 ? "text-up" : opex <= 0.25 ? "text-warn" : "text-down";

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
      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1fr_360px] lg:gap-8">
        {/* The money. */}
        <div className="min-w-0">
          {/* One calm row: what this number is, then the machine's state + mode. */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-quiet">
              Paper net P&amp;L
            </span>
            <span className="ml-auto flex items-center gap-1.5">
              <Badge variant={stateVariant}>
                {running ? <Play className="size-3" /> : status.paused ? <Pause className="size-3" /> : null}
                {stateLabel}
              </Badge>
              <Badge variant={status.live_enabled ? "info" : "muted"}>{modeLabel}</Badge>
            </span>
          </div>

          {/* The hero figure — the single largest number on the page. */}
          <div className={cn("mt-3 text-[44px] font-semibold leading-none tracking-tight tabular sm:text-[56px]", valueColor)}>
            {overviewConnected ? formatUsd(pnl) : "—"}
          </div>
          <p className="mt-3 max-w-md text-[12.5px] leading-relaxed text-muted">{subline}</p>

          {/* A thin truth-rail under the figure: the running cadence + the operating-cost ratio. */}
          <dl className="mt-5 flex flex-wrap items-center gap-x-7 gap-y-2 border-t border-border/50 pt-4">
            <div className="min-w-0">
              <dt className="text-[10.5px] font-medium uppercase tracking-[0.1em] text-quiet">Last cycle</dt>
              <dd className="mt-1 text-[13px] text-foreground">
                {statusConnected && lastTick ? (
                  <>
                    {lastTick} <span className="text-quiet">· {status.cycles_run} run</span>
                  </>
                ) : (
                  <span className="text-quiet">status unknown</span>
                )}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-[10.5px] font-medium uppercase tracking-[0.1em] text-quiet">Cost vs alpha</dt>
              <dd className={cn("mt-1 text-[13px] tabular", opexTone)}>{opexLabel}</dd>
            </div>
          </dl>
        </div>

        {/* The ONE chart — the real equity curve at hero scale. Renders nothing on day 0 (honest). */}
        <div className="flex shrink-0 flex-col items-stretch gap-3">
          {hasCurve ? (
            <div className="rounded-lg border border-border/50 bg-surface-2/20 p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[10.5px] font-medium uppercase tracking-[0.1em] text-quiet">Equity curve</span>
                <span className="text-[10.5px] text-quiet">net of fees</span>
              </div>
              <Sparkline
                values={equityValues}
                width={336}
                height={92}
                strokeWidth={2}
                ariaLabel="paper equity curve, net of fees"
                className="w-full"
              />
            </div>
          ) : (
            <div className="flex h-[126px] items-center justify-center rounded-lg border border-dashed border-border/60 bg-surface-2/20 px-4 text-center text-[11.5px] leading-relaxed text-quiet">
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
