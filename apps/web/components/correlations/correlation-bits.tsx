// Shared, page-local primitives for the /correlations surface — the formatters, the diverging
// IC color scale, the IC pill, the non-causal flag, and the small column label. Kept here so the
// server page, the heatmap, the findings table, and the decay rail all render IDENTICAL, calm,
// money-truth-restrained visuals. These compose the design-system tokens (globals.css); they never
// fabricate a value — every helper only formats / colors a number it is handed.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// The BH-FDR q used by the scan — surfaced so the UI can say what "survived" means out loud.
export const FDR_Q = 0.1;

// ── Formatters ───────────────────────────────────────────────────────────────────────────────────
// Signed IC, always 3 decimals so the column reads as a clean tabular block (e.g. +0.082 / −0.140).
export function fmtIc(ic: number): string {
  if (!Number.isFinite(ic)) return "—";
  const s = ic.toFixed(3);
  return ic > 0 ? `+${s}` : s; // toFixed already prints the minus sign for negatives
}

// p-value: small p's collapse to "<0.001" so the column never shows a noisy 0.0000004.
export function fmtP(p: number): string {
  if (!Number.isFinite(p)) return "—";
  if (p < 0.001) return "<0.001";
  return p.toFixed(3);
}

// A bar count like "12,480" — observation counts read faster grouped.
export function fmtN(n: number): string {
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : "—";
}

// "h=6" style horizon tag.
export function fmtHorizon(h: number): string {
  return `h=${h}`;
}

// ── Diverging IC color ─────────────────────────────────────────────────────────────────────────
// Money-truth restraint: a near-zero IC is near-neutral; sign drives hue (green = positive,
// red = negative), magnitude drives opacity. We cap the magnitude reference at IC_CAP so a single
// freakishly strong (likely spurious) IC doesn't blow out the whole scale. Returns inline-style
// background/foreground strings for a heatmap cell — NOT a fabricated value, just a faithful encoding.
const IC_CAP = 0.2;

export function icCell(ic: number): { background: string; color: string } {
  if (!Number.isFinite(ic) || ic === 0) {
    return { background: "var(--color-surface-2)", color: "var(--color-quiet)" };
  }
  const mag = Math.min(1, Math.abs(ic) / IC_CAP);
  // Floor the fill so even a weak-but-real IC is visible; cap so strong cells stay calm, not loud.
  const alpha = (0.08 + mag * 0.42).toFixed(3);
  const hue = ic > 0 ? "var(--color-up)" : "var(--color-down)";
  // Text turns from muted → foreground as the cell darkens, keeping contrast honest at every level.
  const color = mag > 0.45 ? "var(--color-foreground)" : "var(--color-muted)";
  return { background: `color-mix(in oklch, ${hue} ${Number(alpha) * 100}%, transparent)`, color };
}

// ── IC pill ───────────────────────────────────────────────────────────────────────────────────
// A signed IC chip: green for positive, red for negative, neutral for ~0. Survivors get a brighter
// ring; everything else stays calm. This is the table's primary number.
export function IcPill({ ic, survived = false }: { ic: number; survived?: boolean }) {
  const pos = ic > 0;
  const neutral = !Number.isFinite(ic) || ic === 0;
  return (
    <span
      className={cn(
        "inline-flex items-center justify-end rounded-md px-1.5 py-0.5 text-[12.5px] font-semibold tabular",
        neutral
          ? "text-quiet"
          : pos
            ? "text-up"
            : "text-down",
        survived && !neutral && (pos ? "bg-up/[0.08] ring-1 ring-up/25" : "bg-down/[0.08] ring-1 ring-down/25")
      )}
    >
      {fmtIc(ic)}
    </span>
  );
}

// ── FDR survival pill ────────────────────────────────────────────────────────────────────────
// "survived" (the candidate) vs a calm dash. Survival is propose-only — a candidate hypothesis, NOT
// an edge — so the copy never overclaims.
export function FdrPill({ survived }: { survived: boolean }) {
  return survived ? (
    <span className="inline-flex items-center gap-1 rounded-full border border-up/30 bg-up/[0.09] px-2 py-0.5 text-[11px] font-medium text-up">
      <span className="size-1.5 rounded-full bg-up" aria-hidden />
      survived
    </span>
  ) : (
    <span className="text-[12px] tabular text-quiet">—</span>
  );
}

// ── Non-causal flag ───────────────────────────────────────────────────────────────────────────
// The honest causal-trust tell. A non-empty `deflated_note` flags a feature whose IC must be read
// with suspicion: a known-false / orthogonality control (a strong IC here is data-snooping, not an
// edge) or a low-confidence prior. Shown PLAINLY — "non-causal control — Gate disposes" — never
// buried. Empty note => nothing rendered (a plain feature).
export function isNonCausal(note: string): boolean {
  return note.toUpperCase().includes("NON-CAUSAL");
}

export function NonCausalFlag({ note, className }: { note: string; className?: string }) {
  if (!note) return null;
  const nonCausal = isNonCausal(note);
  return (
    <span
      title={note}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-medium",
        nonCausal
          ? "border-warn/30 bg-warn/[0.08] text-warn"
          : "border-border bg-surface-2/60 text-quiet",
        className
      )}
    >
      <span className={cn("size-1.5 rounded-full", nonCausal ? "bg-warn" : "bg-quiet")} aria-hidden />
      {nonCausal ? "non-causal control — Gate disposes" : "low-confidence — Gate disposes"}
    </span>
  );
}

// ── Small column label ───────────────────────────────────────────────────────────────────────
export function ColumnLabel({ children }: { children: ReactNode }) {
  return <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-quiet">{children}</span>;
}
