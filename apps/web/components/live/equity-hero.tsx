"use client";

// The dashboard equity hero (Iris Bento `.dash-hero`, shared by Paper + Live). A faithful port of the
// mockup's equityBlock(): a hero label + headline value + signed delta, a `.tf-seg` 7D/30D/All range
// selector (1D is dropped — a single point is meaningless; see RANGES below), and the interactive EquityChart
// whose crosshair scrub drives the headline (setHead/restoreHead).
//
// HONESTY: it is fed ONLY the real `equity_curve` (Point[] {ts,value}) the engine returns. With an empty
// series the EquityChart renders its own honest empty state and the headline shows "—" — never a fabricated
// line or number. The 1D/7D/30D/All buttons slice the SAME real series by tail length (no intraday
// fabrication): "1D" → last point only is meaningless, so ranges map to trailing-N points of the real curve.

import { useMemo, useState } from "react";
import type { Point } from "@cosmu/contracts-ts";
import { EquityChart } from "@/components/charts/equity-chart";
import { cn, formatUsd } from "@/lib/utils";

type Range = "7D" | "30D" | "All";

const RANGES: { key: Range; label: string; days: number | null }[] = [
  { key: "7D", label: "7D", days: 7 },
  { key: "30D", label: "30D", days: 30 },
  { key: "All", label: "All", days: null }
];

function fmtDate(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function EquityHero({
  label,
  curve,
  color
}: {
  label: string;
  curve: Point[];
  /** Optional fixed line colour; omit to derive up/down from the series direction. */
  color?: string;
}) {
  const [range, setRange] = useState<Range>("30D");
  const [scrub, setScrub] = useState<number>(-1);

  // Slice the REAL curve by trailing length for the selected range. No fabricated intraday points.
  const sliced = useMemo(() => {
    const r = RANGES.find((x) => x.key === range)!;
    if (r.days === null) return curve;
    return curve.slice(-r.days);
  }, [curve, range]);

  const values = sliced.map((p) => p.value);
  const labels = sliced.map((p) => fmtDate(p.ts));
  const n = values.length;

  // Headline = scrubbed point when hovering, else the last real point. "—" when there is no real series.
  const headIdx = scrub >= 0 && scrub < n ? scrub : n - 1;
  const headVal = n > 0 ? values[headIdx] : null;
  const base = n > 0 ? values[0] : null;
  const delta = headVal !== null && base !== null ? headVal - base : null;
  const deltaPct = delta !== null && base ? (delta / base) * 100 : null;

  return (
    <div className="card dh" style={{ padding: "14px 16px" }}>
      <div className="hero-top">
        <div>
          <div className="hero-label">{label}</div>
          <div>
            <span className="hero-val tab">{headVal === null ? "—" : formatUsd(headVal)}</span>
            {delta !== null ? (
              <span className={cn("hero-delta tab", delta >= 0 ? "up" : "dn")}>
                {delta >= 0 ? "+" : "-"}
                {formatUsd(Math.abs(delta))}
                {deltaPct !== null ? ` (${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%)` : ""}
              </span>
            ) : (
              <span className="hero-delta tab quiet">—</span>
            )}
          </div>
        </div>
        <div className="tf-seg">
          {RANGES.map((r) => (
            <button key={r.key} className={cn(range === r.key && "on")} onClick={() => setRange(r.key)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <EquityChart
        values={values}
        labels={labels}
        color={color}
        height={160}
        axis
        onScrub={setScrub}
        emptyHint="No equity curve yet — this fills in once the engine reports a real net-of-fee series. Nothing here is fabricated."
      />
    </div>
  );
}
