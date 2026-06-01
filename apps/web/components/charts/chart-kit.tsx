// module: shared chart primitives for the Recharts-based chart kit. Themed to the
// "Obsidian Iris" OKLch tokens (see app/globals.css) so every chart looks native to the
// design — no clashing default Recharts palette. Provides: the token color map, a themed
// tooltip shell, an honest empty state, a reduced-motion hook, and common axis/grid props.
//
// All charts are client components (Recharts renders client-side). Pages stay server
// components and pass already-fetched data in.
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// The design tokens, referenced as CSS variables so light/dark theme flips for free.
export const chartColors = {
  iris: "var(--color-iris)",
  irisSoft: "var(--color-iris-soft)",
  up: "var(--color-up)",
  down: "var(--color-down)",
  gold: "var(--color-gold)",
  info: "var(--color-info)",
  warn: "var(--color-warn)",
  foreground: "var(--color-foreground)",
  muted: "var(--color-muted)",
  quiet: "var(--color-quiet)",
  surface: "var(--color-surface)",
  surface2: "var(--color-surface-2)",
  border: "var(--color-border)"
} as const;

// A small donut/category palette drawn only from on-theme tokens.
export const categoryPalette = [
  "var(--color-iris)",
  "var(--color-info)",
  "var(--color-gold)",
  "var(--color-up)",
  "var(--color-iris-soft)",
  "var(--color-down)"
];

// Respect the OS reduce-motion setting: charts skip entry animation when set.
export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

// Shared Recharts grid + axis styling so every chart matches.
export const gridProps = {
  stroke: "var(--color-border)",
  strokeOpacity: 0.5,
  strokeDasharray: "2 6",
  vertical: false
} as const;

export const axisProps = {
  stroke: "var(--color-border)",
  tick: { fill: "var(--color-quiet)", fontSize: 11 },
  tickLine: false,
  axisLine: false
} as const;

// Themed tooltip card used by the custom Recharts tooltip renderers.
export function TooltipShell({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface px-3 py-2 text-[11.5px] leading-relaxed shadow-card",
        className
      )}
    >
      {children}
    </div>
  );
}

export function TooltipRow({ label, value, color }: { label: ReactNode; value: ReactNode; color?: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex items-center gap-1.5 text-quiet">
        {color ? <span className="size-2 shrink-0 rounded-[3px]" style={{ background: color }} /> : null}
        {label}
      </span>
      <span className="tabular font-medium text-foreground">{value}</span>
    </div>
  );
}

// Honest empty state — shown when there is no data to plot (never a fabricated curve).
export function ChartEmpty({
  icon,
  title = "No data yet",
  hint,
  height = 240
}: {
  icon?: ReactNode;
  title?: string;
  hint?: ReactNode;
  height?: number;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-1.5 text-center"
      style={{ height }}
    >
      {icon ? <div className="text-quiet">{icon}</div> : null}
      <div className="text-[13px] text-muted">{title}</div>
      {hint ? <div className="max-w-sm text-[11.5px] text-quiet">{hint}</div> : null}
    </div>
  );
}
