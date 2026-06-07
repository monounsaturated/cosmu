"use client";

// module: ExplorerChart — the Strategy Explorer price/equity chart built on TradingView
// lightweight-charts. Two stacked panes:
//   • Pane 0 (tall): equity curve — GROSS (dashed iris) and NET (solid emerald/rose)
//     plotted as line series. Entry markers = up triangles (emerald), exits = down
//     triangles (rose). Overlay mode: second asset's curve in gold, dashed.
//   • Pane 1 (slim): signal line (placeholder, future: per-bar signal from engine).
//
// Design rules:
//   – Reads OKLch design tokens so light/dark flip for free.
//   – Honest empty state — never fabricates a curve.
//   – Browser-only (dynamic import inside useEffect, SSR safe).
//   – Handles unmount + theme changes with clean teardown.
//   – Auto-resize via ResizeObserver.

import { useEffect, useMemo, useRef, useState } from "react";
import { TrendingUp } from "lucide-react";
import type {
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import type { ExplorerPoint, ExplorerTrade } from "@cosmu/contracts-ts";
import { ChartEmpty } from "./chart-kit";
import { cn, formatPct } from "@/lib/utils";

// ── Type aliases ────────────────────────────────────────────────────────────
type Range = "1M" | "3M" | "All";
const RANGES: { key: Range; days: number | null }[] = [
  { key: "1M", days: 30 },
  { key: "3M", days: 90 },
  { key: "All", days: null },
];

// Read an OKLch design token off the document.
function token(name: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

// Map ExplorerPoints → lightweight-charts line data (ascending, unique ts, finite values).
function toLineSeries(
  points: ExplorerPoint[],
  field: "gross" | "net"
): { time: UTCTimestamp; value: number }[] {
  const byTime = new Map<number, number>();
  for (const p of points) {
    const ms = Date.parse(p.ts);
    if (Number.isNaN(ms)) continue;
    const v = p[field];
    if (!Number.isFinite(v)) continue;
    byTime.set(Math.floor(ms / 1000), v);
  }
  return [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
}

// Build series markers (entry=up triangle, exit=down triangle) from fills.
function toMarkers(trades: ExplorerTrade[]): SeriesMarker<Time>[] {
  return trades
    .map((t) => {
      const ms = Date.parse(t.ts);
      if (Number.isNaN(ms)) return null;
      const isBuy = t.side === "buy";
      return {
        time: Math.floor(ms / 1000) as UTCTimestamp,
        position: (isBuy ? "belowBar" : "aboveBar") as "belowBar" | "aboveBar",
        color: isBuy ? token("--color-up") : token("--color-down"),
        shape: (isBuy ? "arrowUp" : "arrowDown") as "arrowUp" | "arrowDown",
        text: isBuy ? "B" : "S",
        size: 1,
      };
    })
    .filter(Boolean) as SeriesMarker<Time>[];
}

// Slice points to a time-range window.
function sliceDays(
  pts: { time: UTCTimestamp; value: number }[],
  days: number | null
): { time: UTCTimestamp; value: number }[] {
  if (!days || pts.length === 0) return pts;
  const cutoff = (pts[pts.length - 1].time as number) - days * 86400;
  return pts.filter((p) => (p.time as number) >= cutoff);
}

// ── Props ────────────────────────────────────────────────────────────────────
export interface ExplorerChartProps {
  equityCurve: ExplorerPoint[];
  trades: ExplorerTrade[];
  /** Optional second asset's curve for overlay comparison. */
  overlayEquity?: ExplorerPoint[];
  overlayLabel?: string;
  height?: number;
  paneHeight?: number;
}

export function ExplorerChart({
  equityCurve,
  trades,
  overlayEquity,
  overlayLabel,
  height = 340,
  paneHeight = 90,
}: ExplorerChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const grossRef = useRef<ISeriesApi<"Line"> | null>(null);
  const netRef = useRef<ISeriesApi<"Line"> | null>(null);
  const overlayRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const [range, setRange] = useState<Range>("All");
  const [hover, setHover] = useState<{ gross: number; net: number } | null>(null);

  const allGross = useMemo(() => toLineSeries(equityCurve, "gross"), [equityCurve]);
  const allNet = useMemo(() => toLineSeries(equityCurve, "net"), [equityCurve]);
  const allOverlay = useMemo(
    () => (overlayEquity ? toLineSeries(overlayEquity, "net") : []),
    [overlayEquity]
  );
  const markers = useMemo((): SeriesMarker<Time>[] => toMarkers(trades), [trades]);

  const days = RANGES.find((r) => r.key === range)?.days ?? null;
  const gross = useMemo(() => sliceDays(allGross, days), [allGross, days]);
  const net = useMemo(() => sliceDays(allNet, days), [allNet, days]);
  const overlay = useMemo(() => sliceDays(allOverlay, days), [allOverlay, days]);

  const hasData = allGross.length >= 2;

  // Tail stats for the header legend
  const lastGross = gross[gross.length - 1]?.value ?? 0;
  const lastNet = net[net.length - 1]?.value ?? 0;
  const baseGross = gross[0]?.value ?? 0;
  const baseNet = net[0]?.value ?? 0;
  const grossPct = baseGross ? ((lastGross - baseGross) / Math.abs(baseGross)) * 100 : 0;
  const netPct = baseNet ? ((lastNet - baseNet) / Math.abs(baseNet)) * 100 : 0;

  const shownGross = hover?.gross ?? lastGross;
  const shownNet = hover?.net ?? lastNet;

  // ── Chart lifecycle ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!hasData || !containerRef.current) return;
    let disposed = false;
    let cleanupTheme: (() => void) | undefined;

    (async () => {
      const lc = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;

      const applyTheme = () => {
        const netUp = lastNet >= 0;
        const netColor = netUp ? token("--color-up") : token("--color-down");
        const irisColor = token("--color-iris");
        const goldColor = token("--color-gold");

        chartRef.current?.applyOptions({
          layout: {
            background: { type: lc.ColorType.Solid, color: "transparent" },
            textColor: token("--color-quiet"),
            fontFamily: getComputedStyle(document.body).fontFamily,
          },
          grid: {
            vertLines: { visible: false },
            horzLines: { color: token("--color-border"), style: lc.LineStyle.Dotted },
          },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, timeVisible: false },
          crosshair: {
            mode: lc.CrosshairMode.Magnet,
            vertLine: {
              color: token("--color-border-strong"),
              labelBackgroundColor: token("--color-surface-2"),
            },
            horzLine: {
              color: token("--color-border-strong"),
              labelBackgroundColor: token("--color-surface-2"),
            },
          },
        });

        grossRef.current?.applyOptions({ color: irisColor });
        netRef.current?.applyOptions({ color: netColor });
        overlayRef.current?.applyOptions({ color: goldColor });
      };

      const chart = lc.createChart(containerRef.current, {
        height,
        autoSize: true,
        handleScale: false,
        handleScroll: false,
      });
      chartRef.current = chart;

      // Gross series — dashed iris line
      const grossSeries = chart.addSeries(lc.LineSeries, {
        lineWidth: 1,
        lineStyle: lc.LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerRadius: 3,
        color: token("--color-iris"),
      });
      grossRef.current = grossSeries;

      // Net series — solid emerald/rose
      const netColor2 = lastNet >= 0 ? token("--color-up") : token("--color-down");
      const netSeries = chart.addSeries(lc.LineSeries, {
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerRadius: 4,
        color: netColor2,
      });
      netRef.current = netSeries;

      // Entry/exit markers via the createSeriesMarkers plugin (lc v5 API)
      markersPluginRef.current = lc.createSeriesMarkers(netSeries, []);

      // Overlay series (gold, dashed) — only if overlay data present
      if (allOverlay.length >= 2) {
        const overlaySeries = chart.addSeries(lc.LineSeries, {
          lineWidth: 1,
          lineStyle: lc.LineStyle.LargeDashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerRadius: 3,
          color: token("--color-gold"),
        });
        overlayRef.current = overlaySeries;
      }

      applyTheme();

      // Crosshair hover → update legend
      chart.subscribeCrosshairMove((param) => {
        const gp = param.seriesData.get(grossSeries) as { value?: number } | undefined;
        const np = param.seriesData.get(netSeries) as { value?: number } | undefined;
        if (!gp && !np) {
          setHover(null);
          return;
        }
        setHover({
          gross: typeof gp?.value === "number" ? gp.value : lastGross,
          net: typeof np?.value === "number" ? np.value : lastNet,
        });
      });

      // Re-theme on light/dark flip
      const observer = new MutationObserver(applyTheme);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      cleanupTheme = () => observer.disconnect();
    })();

    return () => {
      disposed = true;
      cleanupTheme?.();
      markersPluginRef.current?.detach();
      markersPluginRef.current = null;
      chartRef.current?.remove();
      chartRef.current = null;
      grossRef.current = null;
      netRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasData, height]);

  // Push data into series when range or data changes
  useEffect(() => {
    if (!grossRef.current || !netRef.current || !chartRef.current) return;
    grossRef.current.setData(gross);
    netRef.current.setData(net);
    // Entry/exit markers via the v5 plugin
    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers(markers);
    }
    if (overlayRef.current && overlay.length > 0) {
      overlayRef.current.setData(overlay);
    }
    chartRef.current.timeScale().fitContent();
    setHover(null);
  }, [gross, net, overlay, markers]);

  if (!hasData) {
    return (
      <ChartEmpty
        icon={<TrendingUp className="size-5" />}
        title="No equity curve yet"
        hint="Fills are recorded once this strategy has traded in Simulation. Nothing here is fabricated."
        height={height + paneHeight}
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-4">
          {/* GROSS */}
          <div className="flex items-baseline gap-1.5">
            <span className="size-2 shrink-0 rounded-sm border border-dashed border-iris/60" />
            <span className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">Gross</span>
            <span className="tabular text-[13px] font-semibold text-foreground">
              {shownGross >= 0 ? "+" : ""}
              {shownGross.toFixed(2)}
            </span>
            <span className={cn("tabular text-[11.5px]", grossPct >= 0 ? "text-iris-soft" : "text-down")}>
              {formatPct(grossPct)}
            </span>
          </div>
          {/* NET */}
          <div className="flex items-baseline gap-1.5">
            <span className={cn("size-2 shrink-0 rounded-sm", netPct >= 0 ? "bg-up/70" : "bg-down/70")} />
            <span className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">Net</span>
            <span className="tabular text-[13px] font-semibold text-foreground">
              {shownNet >= 0 ? "+" : ""}
              {shownNet.toFixed(2)}
            </span>
            <span className={cn("tabular text-[11.5px]", netPct >= 0 ? "text-up" : "text-down")}>
              {formatPct(netPct)}
            </span>
          </div>
          {/* Overlay label */}
          {overlayLabel && allOverlay.length >= 2 ? (
            <div className="flex items-baseline gap-1.5">
              <span className="size-2 shrink-0 rounded-sm bg-gold/70" />
              <span className="text-[11px] font-medium text-quiet">{overlayLabel} net</span>
            </div>
          ) : null}
        </div>
        {/* Range selector */}
        <div className="flex items-center gap-1.5">
          {hover ? (
            <span className="text-[11px] text-quiet">at crosshair</span>
          ) : null}
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
        </div>
      </div>
      {/* Chart */}
      <div ref={containerRef} style={{ height }} className="w-full" />
      {/* Marker legend */}
      <div className="flex items-center gap-4 text-[11px] text-quiet">
        <span className="flex items-center gap-1">
          <span className="text-up">▲</span> Entry (buy)
        </span>
        <span className="flex items-center gap-1">
          <span className="text-down">▼</span> Exit (sell)
        </span>
        <span className="flex items-center gap-1">
          <span className="border-b border-dashed border-iris/60 w-4 inline-block" /> Gross
        </span>
        <span className="flex items-center gap-1">
          <span className={cn("w-4 inline-block border-b", netPct >= 0 ? "border-up/60" : "border-down/60")} /> Net
        </span>
        {overlayLabel && allOverlay.length >= 2 ? (
          <span className="flex items-center gap-1">
            <span className="border-b border-dashed border-gold/60 w-4 inline-block" /> {overlayLabel}
          </span>
        ) : null}
      </div>
    </div>
  );
}
