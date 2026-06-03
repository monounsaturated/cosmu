// module: EquityCurve — the headline pooled-wallet equity chart, built on Recharts and themed
// to the OKLch tokens. Deliverable #1 of the chart kit. Features:
//   - real tooltip (date + value + cumulative %)
//   - TIME-RANGE selector (1M / 3M / 6M / All) that slices the series client-side
//   - DRAWDOWN SHADING: underwater stretches (below running peak) shaded via ReferenceArea
//   - optional BENCHMARK overlay (e.g. BTC buy-and-hold) as a second line, toggleable
//   - carries the PAPER / DEMO / LIVE money badge (passed in by the caller)
//   - honest empty state when there is no curve
// Client component (Recharts renders client-side); the page stays a server component.
"use client";

import { useMemo, useState } from "react";
import { Coins } from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type { Point } from "@cosmu/contracts-ts";
import {
  axisProps,
  chartColors,
  ChartEmpty,
  gridProps,
  TooltipRow,
  TooltipShell,
  useReducedMotion
} from "./chart-kit";
import { MoneyState, type MoneyMode } from "@/components/ui/money-state";
import { formatPct, formatUsd } from "@/lib/utils";
import { cn } from "@/lib/utils";

type Range = "1M" | "3M" | "6M" | "All";
const RANGES: { key: Range; bars: number | null }[] = [
  { key: "1M", bars: 30 },
  { key: "3M", bars: 90 },
  { key: "6M", bars: 180 },
  { key: "All", bars: null }
];

type Row = {
  ts: string;
  value: number;
  benchmark?: number;
  cumPct: number;
  peak: number;
};

// Contiguous underwater stretches (value strictly below the running peak) → shaded bands.
function drawdownBands(rows: Row[]): { x1: string; x2: string }[] {
  const bands: { x1: string; x2: string }[] = [];
  let start: number | null = null;
  for (let i = 0; i < rows.length; i++) {
    const under = rows[i].value < rows[i].peak - 1e-9;
    if (under && start === null) start = i;
    if ((!under || i === rows.length - 1) && start !== null) {
      const end = under ? i : i - 1;
      bands.push({ x1: rows[start].ts, x2: rows[Math.max(end, start)].ts });
      start = null;
    }
  }
  return bands;
}

export function EquityCurve({
  points,
  benchmark,
  benchmarkLabel = "BTC buy & hold",
  mode,
  height = 280,
  compact = false,
  valueLabel = "Equity"
}: {
  points: Point[];
  benchmark?: Point[];
  benchmarkLabel?: string;
  mode: MoneyMode;
  height?: number;
  compact?: boolean;
  valueLabel?: string;
}) {
  const reduced = useReducedMotion();
  const [range, setRange] = useState<Range>("All");
  const [showBenchmark, setShowBenchmark] = useState(false);

  const hasData = points.length >= 2;

  const rows = useMemo<Row[]>(() => {
    if (!hasData) return [];
    const bars = RANGES.find((r) => r.key === range)?.bars ?? null;
    const sliced = bars ? points.slice(Math.max(0, points.length - bars)) : points;
    const base = sliced[0]?.value || 1;
    const benchBase = benchmark?.[benchmark.length - sliced.length]?.value;
    let peak = -Infinity;
    return sliced.map((p, i) => {
      peak = Math.max(peak, p.value);
      // align the benchmark series to the same tail window when present
      const bRaw = benchmark ? benchmark[benchmark.length - sliced.length + i]?.value : undefined;
      const benchScaled =
        bRaw !== undefined && benchBase ? base * (bRaw / benchBase) : undefined;
      return {
        ts: p.ts,
        value: p.value,
        benchmark: benchScaled,
        cumPct: ((p.value - base) / base) * 100,
        peak
      };
    });
  }, [points, benchmark, range, hasData]);

  if (!hasData) {
    return (
      <ChartEmpty
        icon={<Coins className="size-5" />}
        title="No live data yet"
        hint="The net-across-forward-tests curve renders once the engine has real track records."
        height={height}
      />
    );
  }

  const bands = drawdownBands(rows);
  const up = rows[rows.length - 1].cumPct >= 0;
  const lineColor = up ? chartColors.up : chartColors.down;
  const gradId = compact ? "eq-grad-compact" : "eq-grad-full";

  return (
    <div className="space-y-3">
      {/* Controls: time range + benchmark toggle + money badge */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <div role="tablist" aria-label="Time range" className="inline-flex rounded-md border border-border/70 bg-surface-2/40 p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.key}
                role="tab"
                aria-selected={range === r.key}
                onClick={() => setRange(r.key)}
                className={cn(
                  "rounded-[6px] px-2.5 py-1 text-[11px] font-medium tabular transition-colors",
                  range === r.key ? "bg-iris/15 text-iris-soft" : "text-quiet hover:text-muted"
                )}
              >
                {r.key}
              </button>
            ))}
          </div>
          {benchmark && benchmark.length >= 2 ? (
            <button
              onClick={() => setShowBenchmark((v) => !v)}
              aria-pressed={showBenchmark}
              className={cn(
                "rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
                showBenchmark
                  ? "border-gold/40 bg-gold/12 text-gold"
                  : "border-border/70 bg-surface-2/40 text-quiet hover:text-muted"
              )}
            >
              {benchmarkLabel}
            </button>
          ) : null}
        </div>
        <MoneyState mode={mode} withInfo={false} />
      </div>

      <ResponsiveContainer width="100%" height={height} minWidth={0} debounce={50}>
          <ComposedChart data={rows} margin={{ top: 8, right: 6, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity={0.28} />
                <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="ts" {...axisProps} minTickGap={28} hide={compact} />
            <YAxis
              {...axisProps}
              width={compact ? 0 : 56}
              hide={compact}
              domain={["auto", "auto"]}
              tickFormatter={(v: number) => formatUsd(v, 0)}
            />
            {/* Drawdown shading — underwater stretches below the running peak */}
            {bands.map((b, i) => (
              <ReferenceArea
                key={i}
                x1={b.x1}
                x2={b.x2}
                fill={chartColors.down}
                fillOpacity={0.07}
                ifOverflow="extendDomain"
              />
            ))}
            <Tooltip content={<EquityTooltip valueLabel={valueLabel} benchmarkLabel={benchmarkLabel} />} cursor={{ stroke: chartColors.border, strokeWidth: 1 }} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={lineColor}
              strokeWidth={2.25}
              fill={`url(#${gradId})`}
              dot={false}
              isAnimationActive={!reduced}
              name={valueLabel}
            />
            {showBenchmark && benchmark && benchmark.length >= 2 ? (
              <Line
                type="monotone"
                dataKey="benchmark"
                stroke={chartColors.gold}
                strokeWidth={1.75}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={!reduced}
                name={benchmarkLabel}
                connectNulls
              />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
    </div>
  );
}

type TooltipPayloadItem = { dataKey: string; value: number; payload: Row };
function EquityTooltip({
  active,
  payload,
  label,
  valueLabel,
  benchmarkLabel
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
  valueLabel: string;
  benchmarkLabel: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  const bench = payload.find((p) => p.dataKey === "benchmark")?.value;
  return (
    <TooltipShell>
      <div className="mb-1 text-[11px] text-quiet">{label}</div>
      <div className="space-y-0.5">
        <TooltipRow label={valueLabel} value={formatUsd(row.value, 0)} color={row.cumPct >= 0 ? chartColors.up : chartColors.down} />
        <TooltipRow
          label="Cumulative"
          value={<span className={row.cumPct >= 0 ? "text-up" : "text-down"}>{formatPct(row.cumPct)}</span>}
        />
        {bench !== undefined && bench !== null ? (
          <TooltipRow label={benchmarkLabel} value={formatUsd(bench, 0)} color={chartColors.gold} />
        ) : null}
      </div>
    </TooltipShell>
  );
}
