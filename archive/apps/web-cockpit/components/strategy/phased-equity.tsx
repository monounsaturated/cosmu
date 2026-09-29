"use client";

// module: PhasedEquity — the v18 strat-sheet equity panel (Iris Bento `.psec` → `.eq-head` title +
// `.eqwrap` curve + `.eq-axis`). The honest series is the engine's MARKED scope='track' equity trajectory
// (StrategyDetailResponse.forward_equity) — the track's marked book value over time, NOT a cash-flow curve.
// There is no separate "Backtest / Paper / Live" series on this contract, so we draw the single real marked
// curve and label it plainly. When there are < 2 marked points the EquityChart renders its honest empty
// state — never a fabricated line.

import { useMemo, useState } from "react";
import type { Point } from "@cosmu/contracts-ts";
import { EquityChart } from "@/components/charts/equity-chart";
import { fmtTz, formatUsd } from "@/lib/utils";

export function PhasedEquity({
  paperCurve,
  height = 120,
  label = "Equity — marked value",
  embedded = false
}: {
  // Marked equity trajectory (scope='track' snapshots, marked book value). < 2 points = honest empty.
  paperCurve: Point[];
  height?: number;
  label?: string;
  // `embedded`: render only the chart, with NO outer `.psec` box or `.eq-head` title — used inside the
  // shared EquityPanel, which owns the single box + phase toggle. The hovered value still shows in-chart.
  embedded?: boolean;
}) {
  const values = useMemo(() => paperCurve.map((p) => p.value), [paperCurve]);
  const labels = useMemo(
    () =>
      paperCurve.map((p) => {
        return fmtTz(p.ts, { month: "short", day: "2-digit" });
      }),
    [paperCurve]
  );

  // Scrub mirrors the hovered marked value into the title (honest — it's the real snapshot equity).
  const [hover, setHover] = useState<number>(-1);
  const headValue = hover >= 0 && hover < values.length ? formatUsd(values[hover], 2) : null;

  const chart = (
    <EquityChart
      values={values}
      labels={labels}
      axis
      height={height}
      valueFormat={(i) => formatUsd(values[i], 2)}
      onScrub={setHover}
      emptyHint="No equity curve yet — this fills in once this Version is marked on its track (≥ 2 snapshots)."
    />
  );

  if (embedded) return chart;

  return (
    <div className="psec">
      <div className="eq-head">
        <span className="eq-title-txt">{headValue ? `${label} · ${headValue}` : label}</span>
      </div>
      {chart}
    </div>
  );
}
