// module: FoldBars — small per-backtest OOS-return bar chart for the strategy detail page
// (Deliverable #4). Reads the strategy's backtests[] (wfo / holdout / fold kinds) and plots
// each kind's OOS return; green above zero, red below. Honest empty state if none. Client.
"use client";

import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Backtest } from "@cosmu/contracts-ts";
import { axisProps, chartColors, ChartEmpty, gridProps, TooltipRow, TooltipShell, useReducedMotion } from "./chart-kit";

export function FoldBars({ backtests, height = 200 }: { backtests: Backtest[]; height?: number }) {
  const reduced = useReducedMotion();
  if (!backtests || backtests.length === 0) {
    return <ChartEmpty title="No fold data" hint="Out-of-sample fold returns appear once the strategy is backtested." height={height} />;
  }
  const data = backtests.map((b) => ({
    kind: b.kind,
    oos_pct: b.oos_return * 100,
    passed: b.passed_gates,
    sharpe: b.deflated_sharpe
  }));
  return (
    <ResponsiveContainer width="100%" height={height} minWidth={0} debounce={50}>
        <BarChart data={data} margin={{ top: 12, right: 8, bottom: 0, left: -8 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="kind" {...axisProps} />
          <YAxis {...axisProps} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
          <ReferenceLine y={0} stroke={chartColors.border} />
          <Tooltip cursor={{ fill: "var(--color-surface-2)", fillOpacity: 0.4 }} content={<FoldTooltip />} />
          <Bar dataKey="oos_pct" radius={[6, 6, 0, 0]} isAnimationActive={!reduced} barSize={42}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.oos_pct >= 0 ? chartColors.up : chartColors.down} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
  );
}

type FoldDatum = { kind: string; oos_pct: number; passed: boolean; sharpe: number };
function FoldTooltip({ active, payload }: { active?: boolean; payload?: { payload: FoldDatum }[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <TooltipShell>
      <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-foreground">{d.kind}</div>
      <TooltipRow label="OOS return" value={<span className={d.oos_pct >= 0 ? "text-up" : "text-down"}>{`${d.oos_pct >= 0 ? "+" : ""}${d.oos_pct.toFixed(1)}%`}</span>} />
      <TooltipRow label="Deflated Sharpe" value={d.sharpe.toFixed(2)} />
      <TooltipRow label="Gates" value={d.passed ? "passed" : "blocked"} />
    </TooltipShell>
  );
}
