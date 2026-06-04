"use client";

// module: TvChart — the equity / backtest curve, rendered with TradingView's lightweight-charts. This
// is the "real" financial chart of the cockpit (the dashboard bar/spark primitives live in dash.tsx).
// Features: a TIME-RANGE selector (1M / 3M / 6M / All), a live crosshair legend (value + cumulative %),
// a SIM / LIVE money badge, theme-reactive colours (reads the Obsidian-Iris OKLch tokens and re-applies
// on light/dark flip), auto-resize, and an HONEST empty state — never a fabricated curve.
//
// lightweight-charts is browser-only, so the library is dynamically imported inside an effect (it never
// runs during SSR). The page stays a server component and passes already-fetched points in.

import { useEffect, useMemo, useRef, useState } from "react";
import { Coins } from "lucide-react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { Point } from "@cosmu/contracts-ts";
import { ChartEmpty } from "./chart-kit";
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

type ValueKind = "usd" | "plain";

// Read an OKLch design token off the document so the chart matches the live theme exactly.
function token(name: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

// Map engine points → lightweight-charts data. ts → UTC seconds; ascending + unique (last value wins
// for any duplicate timestamp) as the library requires.
function toSeries(points: Point[]): { time: UTCTimestamp; value: number }[] {
  const byTime = new Map<number, number>();
  for (const p of points) {
    const ms = Date.parse(p.ts);
    if (Number.isNaN(ms) || !Number.isFinite(p.value)) continue;
    byTime.set(Math.floor(ms / 1000), p.value);
  }
  return [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
}

export function TvChart({
  points,
  mode,
  height = 280,
  valueKind = "usd",
  emptyTitle = "No live data yet",
  emptyHint = "The curve renders once the engine has a real track record. Nothing here is fabricated."
}: {
  points: Point[];
  mode: MoneyMode;
  height?: number;
  valueKind?: ValueKind;
  emptyTitle?: string;
  emptyHint?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  // The current window's baseline value, kept in a ref so the (long-lived) crosshair handler always
  // reads the live base — not the value captured when the chart was first created.
  const baseRef = useRef(0);
  const [range, setRange] = useState<Range>("All");
  // The point the crosshair is over (null → show the latest).
  const [hover, setHover] = useState<{ value: number; cumPct: number } | null>(null);

  const all = useMemo(() => toSeries(points), [points]);
  const sliced = useMemo(() => {
    const bars = RANGES.find((r) => r.key === range)?.bars ?? null;
    return bars ? all.slice(Math.max(0, all.length - bars)) : all;
  }, [all, range]);

  const hasData = all.length >= 2;
  const base = sliced[0]?.value ?? 0;
  const last = sliced[sliced.length - 1]?.value ?? 0;
  const lastCumPct = base ? ((last - base) / base) * 100 : 0;
  const up = last >= base;

  const fmt = (v: number) => (valueKind === "usd" ? formatUsd(v, 0) : v.toLocaleString("en-US"));

  // Create the chart once; tear down on unmount.
  useEffect(() => {
    if (!hasData || !containerRef.current) return;
    let disposed = false;
    let cleanupTheme: (() => void) | undefined;

    (async () => {
      const lc = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;

      const applyTheme = (chart: IChartApi, series: ISeriesApi<"Area">) => {
        const line = up ? token("--color-up") : token("--color-down");
        chart.applyOptions({
          layout: {
            background: { type: lc.ColorType.Solid, color: "transparent" },
            textColor: token("--color-quiet"),
            fontFamily: getComputedStyle(document.body).fontFamily
          },
          grid: {
            vertLines: { visible: false },
            horzLines: { color: token("--color-border"), style: lc.LineStyle.Dotted }
          },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, timeVisible: false },
          crosshair: {
            mode: lc.CrosshairMode.Magnet,
            vertLine: { color: token("--color-border-strong"), labelBackgroundColor: token("--color-surface-2") },
            horzLine: { color: token("--color-border-strong"), labelBackgroundColor: token("--color-surface-2") }
          }
        });
        series.applyOptions({
          lineColor: line,
          topColor: `color-mix(in oklab, ${line} 28%, transparent)`,
          bottomColor: `color-mix(in oklab, ${line} 1%, transparent)`
        });
      };

      const chart = lc.createChart(containerRef.current, {
        height,
        autoSize: true,
        handleScale: false,
        handleScroll: false,
        localization: { priceFormatter: (p: number) => fmt(p) }
      });
      const series = chart.addSeries(lc.AreaSeries, {
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerRadius: 4
      });
      chartRef.current = chart;
      seriesRef.current = series;
      applyTheme(chart, series);

      // Live legend: report the hovered point (value + cumulative % vs the window's first point).
      chart.subscribeCrosshairMove((param) => {
        const point = param.seriesData.get(series) as { value?: number } | undefined;
        if (!point || typeof point.value !== "number") {
          setHover(null);
          return;
        }
        const b = baseRef.current;
        setHover({ value: point.value, cumPct: b ? ((point.value - b) / b) * 100 : 0 });
      });

      // Re-theme on light/dark flip (the toggle adds/removes `.light` on <html>).
      const observer = new MutationObserver(() => applyTheme(chart, series));
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      cleanupTheme = () => observer.disconnect();
    })();

    return () => {
      disposed = true;
      cleanupTheme?.();
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // Recreate only when the data presence flips; data + range + theme are pushed via the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasData, height]);

  // Push the current (range-sliced) data into the series; re-fit the visible range.
  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return;
    baseRef.current = sliced[0]?.value ?? 0;
    seriesRef.current.setData(sliced);
    chartRef.current.timeScale().fitContent();
    setHover(null);
  }, [sliced]);

  // Recolour up/down when the tail of the window crosses zero return.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const line = up ? token("--color-up") : token("--color-down");
    series.applyOptions({
      lineColor: line,
      topColor: `color-mix(in oklab, ${line} 28%, transparent)`,
      bottomColor: `color-mix(in oklab, ${line} 1%, transparent)`
    });
  }, [up]);

  if (!hasData) {
    return <ChartEmpty icon={<Coins className="size-5" />} title={emptyTitle} hint={emptyHint} height={height} />;
  }

  const shownValue = hover?.value ?? last;
  const shownCum = hover?.cumPct ?? lastCumPct;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Live legend — the rich detail-on-demand: value + cumulative % at the crosshair. */}
        <div className="flex items-baseline gap-2">
          <span className="tabular text-lg font-semibold tracking-tight text-foreground">{fmt(shownValue)}</span>
          <span className={cn("tabular text-[12.5px] font-medium", shownCum >= 0 ? "text-up" : "text-down")}>
            {formatPct(shownCum)}
          </span>
          <span className="text-[11px] text-quiet">{hover ? "at crosshair" : "latest"}</span>
        </div>
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
          <MoneyState mode={mode} withInfo={false} />
        </div>
      </div>
      <div ref={containerRef} style={{ height }} className="w-full" />
    </div>
  );
}
