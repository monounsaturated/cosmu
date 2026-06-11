import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { GaugeBar } from "@/components/ui/viz";
import { DivergenceBadge } from "@/components/forward-test/divergence-badge";
import { cn, formatPct } from "@/lib/utils";

// The Simulation track card — the hero of this surface. ONE funded track, read top-to-bottom:
//   1. Identity: name + asset / venue / timeframe, and a link to the full strategy detail.
//   2. Forward equity SINCE FUNDING: the REAL marked net-of-fee return (forward_return_pct). This is the
//      only number that proves the edge holds forward — it is the hero, money-truth coloured. A just-funded
//      track that hasn't accrued a marked number reads an honest "day 0 · +0.00%", never the backtest %.
//   3. Forward age toward live-ready: the day clock + a maturity gauge filling toward +30 days. The marker
//      sits at the live-ready line; the bar is honestly empty for a brand-new track.
//   4. Divergence: the integrated SIM-vs-backtest badge (tracking / diverging / not enough data).
//   5. Backtest OOS: a QUIET secondary reference, explicitly labelled historical — never read as forward.
//
// HONESTY: nothing here is fabricated. forward_return_pct === null → the day-0 zero state. The backtest
// number is visually demoted so it can never be misread as forward performance (the operator's flag).
const LIVE_READY_DAYS = 30;

export function TrackCard({ row }: { row: LeaderboardRow }) {
  const days = Number.isFinite(row.forward_age_days) ? row.forward_age_days : 0;
  const whole = Math.max(0, Math.floor(days));
  const marked = typeof row.forward_return_pct === "number" && Number.isFinite(row.forward_return_pct);
  const fwd = marked ? (row.forward_return_pct as number) : 0;
  const fwdTone = !marked ? "text-quiet" : fwd > 0 ? "text-up" : fwd < 0 ? "text-down" : "text-muted";

  return (
    <div className="card-grad rounded-lg border border-border/70 p-4 shadow-card sm:p-5">
      {/* Identity row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/strategy/${row.version_id}`}
            className="group inline-flex items-center gap-1.5 text-[13.5px] font-semibold tracking-tight text-foreground hover:text-iris-soft"
          >
            <span className="truncate">{row.name}</span>
            <ArrowRight className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-quiet">
            <span className="text-muted">{row.asset_class}</span>
            <span aria-hidden>·</span>
            <span>{row.venue}</span>
            <span aria-hidden>·</span>
            <span className="tabular">{row.timeframe}</span>
            <span aria-hidden>·</span>
            <span>{row.signal_family_label}</span>
          </div>
        </div>
        <DivergenceBadge row={row} />
      </div>

      {/* Forward equity since funding — the hero number */}
      <div className="mt-4 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">
            Forward since funding
            <Tooltip content="The REAL net-of-fee return marked to market since the Gate funded this track. This is the only number that proves the edge holds out-of-sample in real time. A just-funded track reads day 0 · +0.00% until it accrues forward history; a flat or losing track shows its true number." />
          </div>
          <div className={cn("mt-1 text-3xl font-semibold tracking-tight tabular", fwdTone)}>
            {marked ? formatPct(fwd) : "+0.00%"}
          </div>
        </div>
        {/* Backtest OOS — quiet, demoted, explicitly historical */}
        <div className="text-right">
          <div className="flex items-center justify-end gap-1.5 text-[10.5px] uppercase tracking-wide text-quiet">
            Backtest OOS
            <Tooltip content="Out-of-sample backtest return — HISTORICAL, gross. It proves nothing forward. Do not read it as forward performance." />
          </div>
          <div className="mt-0.5 tabular text-[13px] font-medium text-muted">{formatPct(row.track_return_pct)}</div>
        </div>
      </div>

      {/* Forward age toward live-ready */}
      <div className="mt-4 space-y-1.5">
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-muted">Forward age</span>
          <span className="tabular text-quiet">
            <span className="font-medium text-foreground">day {whole}</span> / {LIVE_READY_DAYS} to live-ready
          </span>
        </div>
        <GaugeBar
          value={whole}
          max={LIVE_READY_DAYS}
          marker={1}
          tone={row.live_ready ? "up" : "iris"}
          height={8}
        />
        <div className="flex items-center justify-between">
          <span className={cn("text-[10.5px] uppercase tracking-wide", row.live_ready ? "text-up" : "text-quiet")}>
            {row.live_ready ? "matured · live-ready at +30d" : marked ? "maturing" : "no forward yet"}
          </span>
          {row.live_ready ? (
            <Badge variant="up">live-ready</Badge>
          ) : null}
        </div>
      </div>
    </div>
  );
}
