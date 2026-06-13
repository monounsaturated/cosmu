"use client";

// module: PhasedEquity — the v18 strat-sheet equity panel (Iris Bento `.psec` → `.eq-head` title +
// `.eqwrap` curve + `.eq-axis`). The strategy-detail contract carries ONLY the trade blotter, so the one
// honest series we can draw is the realized cash-flow curve derived upstream from the real fills. There is
// no separate "Backtest / Paper / Live" series on this contract, so we do NOT fake a phase selector with
// fabricated curves — we draw the single real curve and label it plainly. When there are < 2 fills the
// EquityChart renders its honest empty state — never a fabricated line.

import { useMemo, useState } from "react";
import type { Point } from "@cosmu/contracts-ts";
import { EquityChart } from "@/components/charts/equity-chart";
import { formatUsd } from "@/lib/utils";

export function PhasedEquity({
  paperCurve,
  height = 120,
  label = "Equity — realized P&L"
}: {
  // Forward (paper) equity curve, derived from real fills upstream. < 2 points = honest empty.
  paperCurve: Point[];
  height?: number;
  label?: string;
}) {
  const values = useMemo(() => paperCurve.map((p) => p.value), [paperCurve]);
  const labels = useMemo(
    () =>
      paperCurve.map((p) => {
        const d = new Date(p.ts);
        return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
      }),
    [paperCurve]
  );

  // Scrub mirrors the hovered cumulative value into the title (honest — it's the real series value).
  const [hover, setHover] = useState<number>(-1);
  const headValue =
    hover >= 0 && hover < values.length
      ? `${values[hover] >= 0 ? "+" : "-"}${formatUsd(Math.abs(values[hover]), 2)}`
      : null;

  return (
    <div className="psec">
      <div className="eq-head">
        <span className="eq-title-txt">{headValue ? `${label} · ${headValue}` : label}</span>
      </div>
      <EquityChart
        values={values}
        labels={labels}
        axis
        height={height}
        valueFormat={(i) => `${values[i] >= 0 ? "+" : "-"}${formatUsd(Math.abs(values[i]), 2)}`}
        onScrub={setHover}
        emptyHint="No equity curve yet — this fills in once this Version has ≥ 2 fills on its track."
      />
    </div>
  );
}
