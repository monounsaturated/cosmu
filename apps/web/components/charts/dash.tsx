// module: the dashboard primitive kit — Tremor / shadcn-style building blocks for the cockpit's
// data-rich widgets. These are the lightweight, on-theme dashboard pieces (the financial equity/
// backtest curve lives in tv-chart.tsx). All pure + theme-token coloured; safe in server components.
//   · BarList  — Tremor's signature labelled horizontal bars (funnels, lineage, rankings).
//   · Funnel   — a staged conversion funnel with step-to-step retention %.
//   · Spark    — a compact inline sparkline (trend at a glance).

import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type BarTone = "iris" | "up" | "down" | "info" | "warn" | "gold" | "muted";

const barBg: Record<BarTone, string> = {
  iris: "bg-iris/70",
  up: "bg-up/70",
  down: "bg-down/70",
  info: "bg-info/70",
  warn: "bg-warn/70",
  gold: "bg-gold/70",
  muted: "bg-border-strong"
};

export interface BarListItem {
  name: ReactNode;
  value: number;
  /** Optional right-aligned display value (defaults to value.toLocaleString()). */
  display?: ReactNode;
  /** Optional small sub-label under the name. */
  sub?: ReactNode;
  tone?: BarTone;
  href?: string;
}

// Tremor-style bar list: each row's bar width is proportional to the largest value.
export function BarList({ data, className }: { data: BarListItem[]; className?: string }) {
  const max = Math.max(...data.map((d) => Math.abs(d.value)), 1);
  return (
    <div className={cn("space-y-1.5", className)}>
      {data.map((d, i) => {
        const pct = Math.max(2, (Math.abs(d.value) / max) * 100);
        const inner = (
          <div className="relative overflow-hidden rounded-md border border-border/40 bg-surface-2/20 px-3 py-2">
            <div
              className={cn("absolute inset-y-0 left-0 rounded-md opacity-50 transition-all duration-500", barBg[d.tone ?? "iris"])}
              style={{ width: `${pct}%` }}
              aria-hidden
            />
            <div className="relative flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[12.5px] font-medium text-foreground">{d.name}</div>
                {d.sub ? <div className="truncate text-[10.5px] text-quiet">{d.sub}</div> : null}
              </div>
              <span className="tabular shrink-0 text-[12.5px] font-semibold text-foreground">
                {d.display ?? d.value.toLocaleString("en-US")}
              </span>
            </div>
          </div>
        );
        return d.href ? (
          <Link key={i} href={d.href} className="block transition-opacity hover:opacity-90">
            {inner}
          </Link>
        ) : (
          <div key={i}>{inner}</div>
        );
      })}
    </div>
  );
}

export interface FunnelStage {
  label: string;
  value: number;
  tone?: BarTone;
}

// A staged conversion funnel: bar widths scale to the first (largest) stage, and each step after the
// first shows its retention vs the previous step — the honest "where do candidates fall out?" read.
export function Funnel({ stages }: { stages: FunnelStage[] }) {
  const max = Math.max(stages[0]?.value ?? 0, 1);
  return (
    <div className="space-y-2.5">
      {stages.map((s, i) => {
        const pct = Math.max(3, (s.value / max) * 100);
        const prev = i > 0 ? stages[i - 1].value : null;
        const retention = prev && prev > 0 ? Math.round((s.value / prev) * 100) : null;
        return (
          <div key={s.label}>
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-quiet">{s.label}</span>
              <span className="flex items-center gap-2">
                {retention !== null ? (
                  <span className="tabular text-[10px] text-quiet">{retention}% kept</span>
                ) : null}
                <span className="tabular text-[13px] font-semibold text-foreground">{s.value}</span>
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div className={cn("h-full rounded-full transition-all duration-500", barBg[s.tone ?? "iris"])} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Compact inline sparkline. Honest: needs ≥ 2 points or it renders nothing.
export function Spark({ values, tone = "iris", className }: { values: number[]; tone?: BarTone; className?: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 100;
  const h = 24;
  const stroke: Record<BarTone, string> = {
    iris: "var(--color-iris)",
    up: "var(--color-up)",
    down: "var(--color-down)",
    info: "var(--color-info)",
    warn: "var(--color-warn)",
    gold: "var(--color-gold)",
    muted: "var(--color-border-strong)"
  };
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * h}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={cn("h-6 w-full", className)} preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={stroke[tone]} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
