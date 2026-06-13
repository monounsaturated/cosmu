// module: GuardTile — the v18 "guardrail folded into the KPI line" tile. A small KPI box that reads a
// real used/cap guardrail (Daily loss, Max drawdown, Exposure) as a used value, its cap, and a half-arc
// gauge that fills toward the cap. Pure presentation over REAL numbers — it renders only what it is
// handed and never fabricates a reading. Colour escalates with occupancy (mockup `gcol`): ≥85% red,
// ≥60% gold, else up-green — matching the strats-table drawdown arc so the operator reads risk at a glance.
//
// Server-safe (no hooks). The Live page passes the engine's real used/cap; when nothing is live the page
// passes 0 / cap (the honest safe state — every guardrail sits at 0% while disarmed).

import { cn } from "@/lib/utils";

export type GuardUnit = "usd" | "pct";

// Occupancy → semantic colour. Mirrors the mockup's gcol thresholds exactly.
function toneOf(frac: number): { stroke: string; text: string } {
  if (frac >= 0.85) return { stroke: "var(--color-down)", text: "text-down" };
  if (frac >= 0.6) return { stroke: "var(--color-gold)", text: "text-gold" };
  return { stroke: "var(--color-up)", text: "text-up" };
}

function fmtVal(v: number, unit: GuardUnit): string {
  if (unit === "usd") return `$${Math.round(v).toLocaleString("en-US")}`;
  return `${(Math.round(v * 10) / 10).toLocaleString("en-US")}%`;
}

// A 44×24 half-arc gauge filling left→right toward the cap. Same geometry as the mockup's `arc()`.
function Arc({ frac, stroke }: { frac: number; stroke: string }) {
  const W = 44;
  const H = 24;
  const cx = 22;
  const cy = 21;
  const rad = 17;
  const r = Math.min(Math.max(frac, 0), 1);
  const a = Math.PI - r * Math.PI;
  const ax = (cx + rad * Math.cos(a)).toFixed(1);
  const ay = (cy - rad * Math.sin(a)).toFixed(1);
  const largeArc = r > 0.5 ? 1 : 0;
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden>
      <path
        d={`M${cx - rad},${cy} A${rad},${rad} 0 0 1 ${cx + rad},${cy}`}
        fill="none"
        stroke="var(--color-surface-3)"
        strokeWidth={3.5}
        strokeLinecap="round"
      />
      {r > 0 ? (
        <path
          d={`M${cx - rad},${cy} A${rad},${rad} 0 ${largeArc} 1 ${ax},${ay}`}
          fill="none"
          stroke={stroke}
          strokeWidth={3.5}
          strokeLinecap="round"
        />
      ) : null}
    </svg>
  );
}

export function GuardTile({
  label,
  used,
  cap,
  unit
}: {
  label: string;
  used: number;
  cap: number;
  unit: GuardUnit;
}) {
  const frac = cap > 0 ? Math.min(used / cap, 1) : 0;
  const tone = toneOf(frac);
  return (
    <div className="card-grad relative overflow-hidden rounded-lg border border-border/70 p-4 shadow-card">
      <div className="label-eyebrow">{label}</div>
      <div className="mt-2 flex items-center gap-2">
        <span className={cn("text-lg font-bold tabular leading-none", tone.text)}>{fmtVal(used, unit)}</span>
        <span className="whitespace-nowrap text-[11px] text-quiet">/ {fmtVal(cap, unit)}</span>
        <span className="ml-auto shrink-0">
          <Arc frac={frac} stroke={tone.stroke} />
        </span>
      </div>
    </div>
  );
}
