// module: data-viz primitives for the analytics surfaces (Strategies · Strategy detail · Overview ·
// Costs · Live). These turn REAL numeric fields into glanceable visuals — sparklines, gauge/progress
// bars, dense metric cards, tabbed progressive disclosure, and a pass/fail interlock strip — all themed
// to the "Obsidian Iris" OKLch tokens (app/globals.css).
//
// HONESTY CONTRACT: every component here only renders the values it is handed. None fabricate a series,
// pad a curve, or invent a trend. A Sparkline with <2 points renders nothing; a GaugeBar clamps to its
// real fraction; the InterlockStrip shows exactly the gates it is given. Callers pass real engine data
// or an honest empty/zero state — never a placeholder track record.
//
// Client component: Tabs/Sparkline use React hooks (useState/useId). Server pages (Overview, Costs,
// Strategy detail) import these and pass already-fetched data + server-rendered panels as props — the
// standard "client island in a server page" pattern.
"use client";

import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// Semantic tone → CSS token. Restrained, semantic-only color (Vercel/Linear bar): green = good/up,
// red = loss/down, gold = caution, iris = brand/neutral-positive, info = neutral.
export type Tone = "iris" | "up" | "down" | "warn" | "info" | "muted";
const TONE_VAR: Record<Tone, string> = {
  iris: "var(--color-iris)",
  up: "var(--color-up)",
  down: "var(--color-down)",
  warn: "var(--color-warn)",
  info: "var(--color-info)",
  muted: "var(--color-quiet)"
};

// ─── Sparkline ──────────────────────────────────────────────────────────────────────────────────
// A tiny inline-SVG line (optionally area-filled) for per-row / per-card trends. No dependency, no
// axes, no animation — just the shape of a real series. Auto-tones up/down from first→last unless a
// tone is forced. Renders nothing for <2 points (an honest "no trend yet", never a flat fake line).

export function Sparkline({
  values,
  width = 88,
  height = 24,
  tone,
  area = true,
  strokeWidth = 1.5,
  className,
  ariaLabel
}: {
  values: number[];
  width?: number;
  height?: number;
  tone?: Tone;
  area?: boolean;
  strokeWidth?: number;
  className?: string;
  ariaLabel?: string;
}) {
  const gid = useId();
  if (!values || values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const n = values.length;
  // Inset by strokeWidth so the line never clips at the edges.
  const pad = strokeWidth;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const x = (i: number) => pad + (i / (n - 1)) * innerW;
  const y = (v: number) => pad + innerH - ((v - min) / span) * innerH;

  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  const fill = `${line} L${x(n - 1).toFixed(2)},${height} L${x(0).toFixed(2)},${height} Z`;

  // Auto-tone from the real trajectory unless forced.
  const resolved: Tone = tone ?? (values[n - 1] >= values[0] ? "up" : "down");
  const color = TONE_VAR[resolved];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      role="img"
      aria-label={ariaLabel ?? "trend"}
      preserveAspectRatio="none"
    >
      {area ? (
        <>
          <defs>
            <linearGradient id={`spark-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={fill} fill={`url(#spark-${gid})`} stroke="none" />
        </>
      ) : null}
      <path d={line} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
      {/* End-dot marks the latest value — the "now" of the series. */}
      <circle cx={x(n - 1)} cy={y(values[n - 1])} r={strokeWidth + 0.6} fill={color} />
    </svg>
  );
}

// ─── GaugeBar ───────────────────────────────────────────────────────────────────────────────────
// A horizontal progress/occupancy bar for "X of cap/limit/target". Clamps to [0,1] of its real
// fraction; optional limit marker (e.g. the 25% drawdown line, or a maturity threshold). Used for caps
// (deployed vs cap), daily-loss vs limit, forward-age toward live_ready, PBO quality, etc.

export function GaugeBar({
  value,
  max,
  tone = "iris",
  height = 6,
  marker,
  className,
  trackClassName
}: {
  value: number;
  max: number;
  tone?: Tone;
  height?: number;
  // Optional limit line as a fraction 0..1 of max (e.g. 1 = the cap itself, or 0.25/0.25=1 for a DD limit).
  marker?: number;
  className?: string;
  trackClassName?: string;
}) {
  const frac = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const pct = frac * 100;
  return (
    <div
      className={cn("relative w-full overflow-hidden rounded-full bg-surface-2", trackClassName, className)}
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{ width: `${Math.max(pct, value > 0 ? 2 : 0)}%`, background: TONE_VAR[tone] }}
      />
      {typeof marker === "number" && marker > 0 && marker <= 1 ? (
        <span
          className="absolute top-0 h-full w-px bg-foreground/55"
          style={{ left: `${marker * 100}%` }}
          aria-hidden
        />
      ) : null}
    </div>
  );
}

// ─── MetricCard ─────────────────────────────────────────────────────────────────────────────────
// Dense KPI card: a primary number with a small label, an optional delta, and an optional inline
// visual (sparkline or gauge) on the right. Reads in one glance — the data-viz-platform "stat tile".

export function MetricCard({
  label,
  value,
  delta,
  hint,
  tone = "iris",
  icon,
  visual,
  className
}: {
  label: string;
  value: ReactNode;
  delta?: { value: string; tone: Tone } | null;
  hint?: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  visual?: ReactNode;
  className?: string;
}) {
  const bar: Record<Tone, string> = {
    iris: "before:bg-iris",
    up: "before:bg-up",
    down: "before:bg-down",
    warn: "before:bg-warn",
    info: "before:bg-info",
    muted: "before:bg-border-strong"
  };
  // Explicit (not interpolated) so Tailwind's JIT keeps these classes — dynamic `text-${tone}` would be purged.
  const deltaText: Record<Tone, string> = {
    iris: "text-iris-soft",
    up: "text-up",
    down: "text-down",
    warn: "text-warn",
    info: "text-info",
    muted: "text-quiet"
  };
  return (
    <div
      className={cn(
        "card-grad relative overflow-hidden rounded-lg border border-border/70 p-4 shadow-card",
        "before:absolute before:left-0 before:top-4 before:bottom-4 before:w-0.5 before:rounded-full",
        bar[tone],
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">{label}</span>
        {icon ? <span className="text-muted">{icon}</span> : null}
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-2xl font-semibold tracking-tight tabular text-foreground">{value}</div>
          {delta ? (
            <div className={cn("mt-1 text-[12px] font-medium tabular", deltaText[delta.tone])}>{delta.value}</div>
          ) : null}
        </div>
        {visual ? <div className="shrink-0 pb-0.5">{visual}</div> : null}
      </div>
      {hint ? <div className="mt-2 text-[12px] leading-snug text-muted">{hint}</div> : null}
    </div>
  );
}

// ─── Tabs ───────────────────────────────────────────────────────────────────────────────────────
// Lightweight, accessible, horizontally-scrollable tabs for progressive disclosure (replaces the
// "expand to dump ALL sections at once" pattern). Uncontrolled by default; only the active panel is
// rendered into the DOM, so the operator sees one focused section at a time instead of a long wall.

export type TabItem = {
  id: string;
  label: ReactNode;
  count?: number;
  content: ReactNode;
};

export function Tabs({
  tabs,
  defaultTab,
  className,
  ariaLabel = "Sections"
}: {
  tabs: TabItem[];
  defaultTab?: string;
  className?: string;
  ariaLabel?: string;
}) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.id);
  const current = tabs.find((t) => t.id === active) ?? tabs[0];
  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={ariaLabel}
        className="-mx-1 flex gap-1 overflow-x-auto rounded-lg border border-border/60 bg-surface-2/30 p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {tabs.map((t) => {
          const isActive = t.id === current?.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActive(t.id)}
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                isActive
                  ? "bg-surface text-foreground shadow-card"
                  : "text-muted hover:bg-surface-2/60 hover:text-foreground"
              )}
            >
              {t.label}
              {typeof t.count === "number" ? (
                <span className={cn("tabular text-[11px]", isActive ? "text-iris-soft" : "text-quiet")}>{t.count}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" className="mt-4">
        {current?.content}
      </div>
    </div>
  );
}

// ─── InterlockStrip ─────────────────────────────────────────────────────────────────────────────
// The Gate verdict as a row of pass/fail interlock chips (a safety-interlock strip), NOT a wall of
// numbers. Each interlock carries a label, its REAL measured value, the threshold it was judged
// against, and a pass boolean — so the operator sees exactly which gate held and which broke.

export type Interlock = {
  label: string;
  value: string;
  threshold?: string;
  pass: boolean;
};

export function InterlockStrip({ interlocks, className }: { interlocks: Interlock[]; className?: string }) {
  if (interlocks.length === 0) return null;
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {interlocks.map((it) => (
        <div
          key={it.label}
          className={cn(
            "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
            it.pass ? "border-up/30 bg-up/[0.07]" : "border-down/30 bg-down/[0.07]"
          )}
        >
          <span
            className={cn("size-1.5 shrink-0 rounded-full", it.pass ? "bg-up" : "bg-down")}
            aria-hidden
          />
          <div className="leading-tight">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-quiet">{it.label}</span>
              <span className={cn("text-[12.5px] font-semibold tabular", it.pass ? "text-foreground" : "text-down")}>
                {it.value}
              </span>
            </div>
            {it.threshold ? <div className="text-[10.5px] tabular text-quiet">{it.threshold}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── MiniBarRow ─────────────────────────────────────────────────────────────────────────────────
// A signed magnitude bar that grows from a centre baseline — green right for positive, red left for
// negative. For dense % columns (net return, OOS by category) where the SIGN and RELATIVE size read
// faster than the digits alone. `max` is the reference magnitude that fills the half-track.

export function SignedBar({
  value,
  max,
  height = 6,
  className
}: {
  value: number;
  max: number;
  height?: number;
  className?: string;
}) {
  const m = max > 0 ? max : 1;
  const frac = Math.min(1, Math.abs(value) / m);
  const pos = value >= 0;
  return (
    <div className={cn("relative w-full rounded-full bg-surface-2", className)} style={{ height }}>
      {/* centre baseline */}
      <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-border-strong/70" aria-hidden />
      <div
        className={cn("absolute top-0 h-full", pos ? "left-1/2 rounded-r-full" : "right-1/2 rounded-l-full")}
        style={{ width: `${(frac * 50).toFixed(1)}%`, background: pos ? TONE_VAR.up : TONE_VAR.down }}
      />
    </div>
  );
}
