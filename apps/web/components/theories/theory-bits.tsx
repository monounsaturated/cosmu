// Page-local primitives for the Theories surface (the machine's experiment memory). These compose the
// shared design-system primitives (Badge, GaugeBar) into the few shapes the Theories page and its list
// repeat — kept here so the page and the client list render identical, calm visuals.
//
// HONESTY CONTRACT (inherited): every helper only renders the value it is handed. The dSR gauge clamps
// to the real fraction; a missing holdout reads "no holdout", never a fabricated zero; the decay test
// is the engine's own numbers, not an invented trend. Nothing here pads a series or softens a verdict.

import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { GaugeBar } from "@/components/ui/viz";
import { cn } from "@/lib/utils";

// The Gate's bar for a real, multiple-testing-survived edge. Single source of truth for the surface.
export const DSR_BAR = 0.95;

// Format a deflated-Sharpe-style number, or an honest em-dash when there is genuinely no value.
export function fmtDsr(v: number | null | undefined): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? v.toFixed(2) : "—";
}

// A theory "decays out-of-sample" when it looked promising in-sample (high dSR) but the holdout turned
// negative — the single most important honesty signal on this surface. Defined once, used everywhere.
export function decaysOutOfSample(t: {
  best_dsr: number;
  best_holdout_dsr: number | null;
}): boolean {
  return (
    t.best_holdout_dsr !== null &&
    Number.isFinite(t.best_holdout_dsr) &&
    t.best_holdout_dsr < 0 &&
    t.best_dsr >= 0.5
  );
}

// ─── VerdictPill ──────────────────────────────────────────────────────────────────────────────────
// The Gate's ruling, as a single terse pill. PASS is the rare, earned green; FAIL is the honest,
// un-alarmed default — a wall of these is the receipt that the Gate is real, not an error state.
export function VerdictPill({ passed, className }: { passed: boolean; className?: string }) {
  return (
    <Badge variant={passed ? "up" : "muted"} className={cn("font-semibold", className)}>
      {passed ? "PASS" : "FAIL"}
    </Badge>
  );
}

// ─── DsrGauge ─────────────────────────────────────────────────────────────────────────────────────
// In-sample deflated-Sharpe probability against the 0.95 Gate bar. The marker sits at the bar so the
// operator sees at a glance how far short (or past) the threshold a theory landed. `size` tunes the
// bar width for the dense list ("sm") vs the summary spotlight ("md").
export function DsrGauge({
  value,
  passed,
  size = "sm",
  className
}: {
  value: number;
  passed: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const clamped = Number.isFinite(value) ? value : 0;
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <GaugeBar
        value={clamped}
        max={1}
        marker={DSR_BAR}
        tone={passed ? "up" : "muted"}
        height={size === "md" ? 8 : 6}
        className={size === "md" ? "w-28" : "w-20"}
      />
      <span className={cn("tabular text-[12px]", passed ? "text-up" : "text-muted")}>
        {fmtDsr(clamped)}
      </span>
    </div>
  );
}

// ─── HoldoutValue ─────────────────────────────────────────────────────────────────────────────────
// The out-of-sample holdout deflated Sharpe, with an honest "no holdout" when none was run and a
// "decays out-of-sample" tag when an in-sample edge did not survive the holdout. Right-aligned so the
// digits line up down a dense column.
export function HoldoutValue({
  theory,
  showTag = true
}: {
  theory: { best_dsr: number; best_holdout_dsr: number | null };
  showTag?: boolean;
}) {
  if (theory.best_holdout_dsr === null) {
    return <span className="tabular text-[12px] text-quiet">no holdout</span>;
  }
  const decays = decaysOutOfSample(theory);
  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={cn(
          "tabular text-[12px]",
          theory.best_holdout_dsr < 0 ? "text-down" : "text-foreground"
        )}
      >
        {fmtDsr(theory.best_holdout_dsr)}
      </span>
      {showTag && decays ? <Badge variant="warn">decays out-of-sample</Badge> : null}
    </div>
  );
}

// ─── ColumnLabel ──────────────────────────────────────────────────────────────────────────────────
// The tiny uppercase caption above a numeric column — Bloomberg-style header for a dense value.
export function ColumnLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("text-[10px] uppercase tracking-wide text-quiet", className)}>{children}</span>
  );
}
