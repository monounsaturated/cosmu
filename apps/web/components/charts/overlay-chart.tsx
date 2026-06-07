"use client";

// module: OverlayChart — premium calm multi-series SVG overlay chart.
//
// Renders a PRICE line (right y-axis, raw values) plus up to two NORMALIZED alt-data
// series (funding rate, social sentiment, any numeric alt-feature) on a shared time
// axis. Optional event dots (fills, regime changes, …) are plotted on the price axis.
//
// Design contract:
//   – Pure SVG, no new chart library, no recharts/lightweight-charts — vanilla geometry.
//   – OKLch design tokens (via CSS variables) so light/dark flip for free.
//   – Tabular tooltip: date + all visible series values aligned in a stable column grid.
//   – Range selector (7D / 1M / 3M / All), honest empty state when data absent.
//   – Event dots with a legend row per type.
//   – ResizeObserver for auto-sizing.
//   – ZERO emojis.
//
// Mount point: the Strategy Explorer /explorer page — inside explorer-client.tsx, below
// the equity-curve card, as an "Alt-data overlay" expandable card. The component is
// intentionally self-contained so it can be dropped anywhere a series array is available.

import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { Activity } from "lucide-react";
import { ChartEmpty } from "./chart-kit";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

/** One timestamped datapoint. ts: ISO-8601 string or Unix ms epoch as string. */
export interface OverlayPoint {
  ts: string;
  value: number;
}

/**
 * A named data series to overlay on the chart.
 * kind="price"    → plotted on the right raw y-axis (dominant, thicker).
 * kind="alt"      → plotted on the left normalized [-1, 1] y-axis (secondary, thinner).
 */
export interface OverlaySeries {
  key: string;
  label: string;
  kind: "price" | "alt";
  /** Color token name (e.g. "--color-iris") or a CSS color string. */
  color: string;
  points: OverlayPoint[];
  /** Unit suffix shown in tooltip, e.g. "%" or "bps". Optional. */
  unit?: string;
}

/** An optional event marker (dot) on the time axis. */
export interface OverlayEvent {
  ts: string;
  label: string;
  /** Color token name or CSS color. Defaults to "--color-warn". */
  color?: string;
  /** Short code shown in the dot (1-2 chars). */
  code?: string;
}

export interface OverlayChartProps {
  series: OverlaySeries[];
  events?: OverlayEvent[];
  height?: number;
  /** Chart area top/bottom padding inside the SVG plot. */
  padY?: number;
  /** Left margin for the alt-data y-axis label; right margin for price y-axis. */
  padLeft?: number;
  padRight?: number;
}

// ── Internal types ────────────────────────────────────────────────────────────

interface ParsedPoint {
  t: number; // Unix seconds
  v: number;
}

type Range = "7D" | "1M" | "3M" | "All";
const RANGES: { key: Range; days: number | null }[] = [
  { key: "7D", days: 7 },
  { key: "1M", days: 30 },
  { key: "3M", days: 90 },
  { key: "All", days: null },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseTs(ts: string): number {
  // Accept ISO-8601 or numeric-string (ms epoch).
  const n = Number(ts);
  if (!Number.isNaN(n) && n > 1e10) return Math.floor(n / 1000); // ms → s
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? NaN : Math.floor(ms / 1000);
}

function parsePoints(raw: OverlayPoint[]): ParsedPoint[] {
  const seen = new Map<number, number>();
  for (const p of raw) {
    const t = parseTs(p.ts);
    if (Number.isNaN(t) || !Number.isFinite(p.value)) continue;
    seen.set(t, p.value);
  }
  return [...seen.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([t, v]) => ({ t, v }));
}

function sliceDays(pts: ParsedPoint[], days: number | null): ParsedPoint[] {
  if (!days || pts.length === 0) return pts;
  const cutoff = pts[pts.length - 1].t - days * 86400;
  return pts.filter((p) => p.t >= cutoff);
}

function clampedDomain(pts: ParsedPoint[]): [number, number] {
  if (pts.length === 0) return [0, 1];
  let lo = Infinity, hi = -Infinity;
  for (const p of pts) {
    if (p.v < lo) lo = p.v;
    if (p.v > hi) hi = p.v;
  }
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.08 || 0.1;
  return [lo - pad, hi + pad];
}

// Normalize a value into [0,1] given domain [lo, hi].
function norm(v: number, lo: number, hi: number): number {
  return hi === lo ? 0.5 : (v - lo) / (hi - lo);
}

// Resolve a color token or pass-through a literal color string.
function resolveColor(token: string): string {
  if (token.startsWith("--")) {
    if (typeof window === "undefined") return "#888";
    return getComputedStyle(document.documentElement).getPropertyValue(token).trim() || "#888";
  }
  return token;
}

// Format a Unix-second timestamp as a short date label.
function fmtDate(t: number): string {
  return new Date(t * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Format a value for the tooltip.
function fmtVal(v: number, unit?: string): string {
  const s =
    Math.abs(v) >= 1000
      ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : Math.abs(v) >= 10
      ? v.toFixed(2)
      : v.toFixed(4);
  return unit ? `${s} ${unit}` : s;
}

// Tick values for a y-axis — 4 ticks between lo and hi.
function yTicks(lo: number, hi: number, count = 4): number[] {
  const step = (hi - lo) / (count - 1);
  return Array.from({ length: count }, (_, i) => lo + i * step);
}

// Format a tick label (short).
function fmtTick(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toFixed(4);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OverlayChart({
  series,
  events = [],
  height = 300,
  padY = 20,
  padLeft = 58,
  padRight = 64,
}: OverlayChartProps) {
  const uid = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [range, setRange] = useState<Range>("All");
  const [cursor, setCursor] = useState<{ x: number; t: number } | null>(null);

  // Observe container width.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 80) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Parse all series once.
  const parsed = series.map((s) => ({
    ...s,
    pts: parsePoints(s.points),
  }));

  const days = RANGES.find((r) => r.key === range)?.days ?? null;
  const sliced = parsed.map((s) => ({ ...s, pts: sliceDays(s.pts, days) }));

  // Identify price vs alt series.
  const priceS = sliced.filter((s) => s.kind === "price");
  const altS = sliced.filter((s) => s.kind === "alt");

  const hasAnyData = sliced.some((s) => s.pts.length >= 2);

  if (!hasAnyData) {
    return (
      <ChartEmpty
        icon={<Activity className="size-5" />}
        title="No data yet"
        hint="Alt-data series appear here once the ingest pipeline has at least two timestamped datapoints. Nothing is fabricated."
        height={height}
      />
    );
  }

  // Shared time domain across all series.
  const allPts = sliced.flatMap((s) => s.pts);
  const tMin = Math.min(...allPts.map((p) => p.t));
  const tMax = Math.max(...allPts.map((p) => p.t));

  // Price y-domain (right axis).
  const allPricePts = priceS.flatMap((s) => s.pts);
  const [priceMin, priceMax] =
    allPricePts.length >= 2 ? clampedDomain(allPricePts) : [0, 1];

  // Alt y-domain (left axis) — normalize each alt series independently to [0, 1] then
  // stack them on a shared [0, 1] plot coordinate. We keep per-series domain for tooltip.
  const altDomains = altS.map((s) => clampedDomain(s.pts));

  // Inner plot dimensions.
  const plotW = width - padLeft - padRight;
  const plotH = height - padY * 2;

  // Map t → x pixel within the plot area.
  const tRange = tMax - tMin || 1;
  function tX(t: number): number {
    return padLeft + ((t - tMin) / tRange) * plotW;
  }

  // Map v → y pixel on price axis (right).
  function priceY(v: number): number {
    return padY + (1 - norm(v, priceMin, priceMax)) * plotH;
  }

  // Map v → y pixel on alt axis (series-specific domain, left).
  function altY(v: number, lo: number, hi: number): number {
    return padY + (1 - norm(v, lo, hi)) * plotH;
  }

  // Parse events.
  const parsedEvents = events
    .map((e) => ({ ...e, t: parseTs(e.ts) }))
    .filter((e) => !Number.isNaN(e.t) && e.t >= tMin && e.t <= tMax);

  // X-axis ticks: ~6 ticks.
  const xTickCount = Math.max(2, Math.min(7, Math.floor(plotW / 90)));
  const xTicks = Array.from({ length: xTickCount }, (_, i) =>
    tMin + (i / (xTickCount - 1)) * tRange
  );

  // Price y-axis ticks (right).
  const priceTicksArr = allPricePts.length >= 2 ? yTicks(priceMin, priceMax) : [];

  // Alt y-axis ticks (left) — use first alt series domain as representative.
  const altDom0 = altDomains[0] ?? [0, 1];
  const altTicksArr = altS.length > 0 ? yTicks(altDom0[0], altDom0[1]) : [];

  // Tooltip: find the nearest datapoint per series for cursor t.
  function nearestVal(pts: ParsedPoint[], t: number): number | null {
    if (pts.length === 0) return null;
    let best = pts[0];
    let bestDist = Math.abs(pts[0].t - t);
    for (const p of pts) {
      const d = Math.abs(p.t - t);
      if (d < bestDist) { best = p; bestDist = d; }
    }
    return best.v;
  }

  function handleSvgMove(e: MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const xPx = e.clientX - rect.left - padLeft;
    const t = tMin + (xPx / plotW) * tRange;
    setCursor({ x: e.clientX - rect.left, t });
  }

  function handleSvgLeave() {
    setCursor(null);
  }

  // Tooltip rows.
  const tooltipRows = cursor
    ? sliced.map((s, i) => {
        const v = nearestVal(s.pts, cursor.t);
        const dom = s.kind === "alt" ? (altDomains[altS.findIndex((a) => a.key === s.key)] ?? [0, 1]) : [priceMin, priceMax];
        return {
          key: s.key,
          label: s.label,
          color: s.color,
          value: v !== null ? fmtVal(v, s.unit) : "—",
          tone: s.kind === "price" ? "price" : (v !== null && v >= 0 ? "pos" : "neg"),
          raw: v,
          dom,
          i,
        };
      })
    : [];

  const tooltipX = cursor ? Math.min(cursor.x + 12, width - 180) : 0;
  const tooltipDate = cursor ? fmtDate(Math.round(cursor.t)) : "";

  // Gradient defs: subtle area fill under each alt series.
  const svgId = uid.replace(/:/g, "");

  return (
    <div className="space-y-3">
      {/* Legend + range picker */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Series legend */}
        <div className="flex flex-wrap items-center gap-3">
          {series.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-quiet">
              <span
                className={cn(
                  "inline-block h-[2px] w-5 rounded-full",
                  s.kind === "price" ? "h-[2.5px]" : "h-[1.5px]"
                )}
                style={{ background: resolveColor(s.color) }}
              />
              {s.label}
              {s.unit ? <span className="text-[10px]">({s.unit})</span> : null}
            </span>
          ))}
          {events.length > 0
            ? [...new Set(events.map((e) => e.label))].slice(0, 4).map((lbl) => {
                const ev = events.find((e) => e.label === lbl);
                return (
                  <span key={lbl} className="flex items-center gap-1 text-[11px] text-quiet">
                    <span
                      className="inline-flex size-3.5 items-center justify-center rounded-full text-[8px] font-bold leading-none text-background"
                      style={{ background: resolveColor(ev?.color ?? "--color-warn") }}
                    >
                      {ev?.code ?? "e"}
                    </span>
                    {lbl}
                  </span>
                );
              })
            : null}
        </div>

        {/* Range selector */}
        <div
          role="tablist"
          aria-label="Time range"
          className="inline-flex rounded-md border border-border/70 bg-surface-2/40 p-0.5"
        >
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

      {/* Chart */}
      <div ref={containerRef} className="relative w-full select-none" style={{ height }}>
        <svg
          width={width}
          height={height}
          className="absolute inset-0 overflow-visible"
          onMouseMove={handleSvgMove}
          onMouseLeave={handleSvgLeave}
        >
          <defs>
            {altS.map((s, i) => (
              <linearGradient
                key={`grad-${s.key}`}
                id={`${svgId}-grad-${i}`}
                x1="0"
                x2="0"
                y1="0"
                y2="1"
              >
                <stop offset="0%" stopColor={resolveColor(s.color)} stopOpacity={0.18} />
                <stop offset="100%" stopColor={resolveColor(s.color)} stopOpacity={0.01} />
              </linearGradient>
            ))}
          </defs>

          {/* Horizontal grid lines */}
          {priceTicksArr.map((v, i) => {
            const y = priceY(v);
            return (
              <line
                key={`hgrid-${i}`}
                x1={padLeft}
                x2={padLeft + plotW}
                y1={y}
                y2={y}
                stroke="var(--color-border)"
                strokeOpacity={0.5}
                strokeDasharray="2 6"
                strokeWidth={0.75}
              />
            );
          })}

          {/* Price y-axis ticks (right) */}
          {priceTicksArr.map((v, i) => {
            const y = priceY(v);
            return (
              <text
                key={`rypt-${i}`}
                x={padLeft + plotW + 8}
                y={y + 4}
                fill="var(--color-quiet)"
                fontSize={9.5}
                fontFamily="inherit"
              >
                {fmtTick(v)}
              </text>
            );
          })}

          {/* Alt y-axis ticks (left) */}
          {altTicksArr.map((v, i) => {
            const y = altY(v, altDom0[0], altDom0[1]);
            return (
              <text
                key={`lypt-${i}`}
                x={padLeft - 6}
                y={y + 4}
                fill="var(--color-quiet)"
                fontSize={9.5}
                textAnchor="end"
                fontFamily="inherit"
              >
                {fmtTick(v)}
              </text>
            );
          })}

          {/* Y-axis labels */}
          {altS.length > 0 ? (
            <text
              x={10}
              y={padY + plotH / 2}
              fill="var(--color-quiet)"
              fontSize={9}
              textAnchor="middle"
              fontFamily="inherit"
              transform={`rotate(-90, 10, ${padY + plotH / 2})`}
            >
              {altS[0].label}{altS[0].unit ? ` (${altS[0].unit})` : ""}
            </text>
          ) : null}
          {priceS.length > 0 ? (
            <text
              x={padLeft + plotW + padRight - 10}
              y={padY + plotH / 2}
              fill="var(--color-quiet)"
              fontSize={9}
              textAnchor="middle"
              fontFamily="inherit"
              transform={`rotate(90, ${padLeft + plotW + padRight - 10}, ${padY + plotH / 2})`}
            >
              {priceS[0].label}{priceS[0].unit ? ` (${priceS[0].unit})` : ""}
            </text>
          ) : null}

          {/* X-axis ticks */}
          {xTicks.map((t, i) => (
            <text
              key={`xt-${i}`}
              x={tX(t)}
              y={height - 3}
              fill="var(--color-quiet)"
              fontSize={9.5}
              textAnchor="middle"
              fontFamily="inherit"
            >
              {fmtDate(t)}
            </text>
          ))}

          {/* Alt area fills */}
          {altS.map((s, i) => {
            if (s.pts.length < 2) return null;
            const [lo, hi] = altDomains[i] ?? [0, 1];
            const pts = s.pts.map((p) => ({
              x: tX(p.t),
              y: altY(p.v, lo, hi),
            }));
            const lineD = pts.map((p, j) => `${j === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
            const baseline = padY + plotH;
            const areaD =
              lineD +
              ` L${pts[pts.length - 1].x.toFixed(1)},${baseline} L${pts[0].x.toFixed(1)},${baseline} Z`;
            return (
              <path
                key={`area-${s.key}`}
                d={areaD}
                fill={`url(#${svgId}-grad-${i})`}
              />
            );
          })}

          {/* Alt data lines */}
          {altS.map((s, i) => {
            if (s.pts.length < 2) return null;
            const [lo, hi] = altDomains[i] ?? [0, 1];
            const transformedPts = s.pts.map((p) => ({
              x: padLeft + ((p.t - tMin) / tRange) * plotW,
              y: altY(p.v, lo, hi),
            }));
            const polyPoints = transformedPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
            return (
              <polyline
                key={`alt-${s.key}`}
                points={polyPoints}
                fill="none"
                stroke={resolveColor(s.color)}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
                opacity={0.85}
              />
            );
          })}

          {/* Price line(s) */}
          {priceS.map((s) => {
            if (s.pts.length < 2) return null;
            const transformedPts = s.pts.map((p) => ({
              x: padLeft + ((p.t - tMin) / tRange) * plotW,
              y: priceY(p.v),
            }));
            const polyPoints = transformedPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
            return (
              <polyline
                key={`price-${s.key}`}
                points={polyPoints}
                fill="none"
                stroke={resolveColor(s.color)}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}

          {/* Event dots */}
          {parsedEvents.map((e, i) => {
            const x = tX(e.t);
            // Snap to price axis if available, else midpoint.
            const yBase = priceS.length > 0
              ? padY + plotH * 0.12
              : padY + plotH / 2;
            const c = resolveColor(e.color ?? "--color-warn");
            return (
              <g key={`ev-${i}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={padY}
                  y2={padY + plotH}
                  stroke={c}
                  strokeWidth={0.75}
                  strokeOpacity={0.35}
                  strokeDasharray="2 4"
                />
                <circle
                  cx={x}
                  cy={yBase}
                  r={7}
                  fill={c}
                  fillOpacity={0.9}
                />
                <text
                  x={x}
                  y={yBase + 3.5}
                  textAnchor="middle"
                  fill="var(--color-background)"
                  fontSize={7.5}
                  fontWeight={700}
                  fontFamily="inherit"
                >
                  {(e.code ?? e.label.slice(0, 1)).toUpperCase()}
                </text>
              </g>
            );
          })}

          {/* Crosshair vertical line */}
          {cursor ? (
            <line
              x1={cursor.x}
              x2={cursor.x}
              y1={padY}
              y2={padY + plotH}
              stroke="var(--color-border-strong)"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
          ) : null}

          {/* Crosshair dots on each series */}
          {cursor
            ? sliced.map((s, i) => {
                const v = nearestVal(s.pts, cursor.t);
                if (v === null || s.pts.length < 2) return null;
                const dom = s.kind === "alt"
                  ? (altDomains[altS.findIndex((a) => a.key === s.key)] ?? [0, 1])
                  : [priceMin, priceMax];
                const y = s.kind === "price" ? priceY(v) : altY(v, dom[0], dom[1]);
                return (
                  <circle
                    key={`dot-${s.key}`}
                    cx={tX(cursor.t)}
                    cy={y}
                    r={s.kind === "price" ? 4 : 3}
                    fill={resolveColor(s.color)}
                    stroke="var(--color-background)"
                    strokeWidth={1.5}
                  />
                );
              })
            : null}
        </svg>

        {/* Tooltip */}
        {cursor && tooltipRows.length > 0 ? (
          <div
            className="pointer-events-none absolute z-10 rounded-lg border border-border bg-surface px-3 py-2 shadow-card"
            style={{ left: tooltipX, top: padY + 4 }}
          >
            <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">
              {tooltipDate}
            </div>
            <table className="w-full border-collapse">
              <tbody>
                {tooltipRows.map((row) => (
                  <tr key={row.key}>
                    <td className="py-[2px] pr-3">
                      <span className="flex items-center gap-1.5 text-[11px] text-quiet">
                        <span
                          className="inline-block h-[2px] w-3.5 rounded-full"
                          style={{ background: resolveColor(row.color) }}
                        />
                        {row.label}
                      </span>
                    </td>
                    <td className="py-[2px] text-right font-mono text-[11.5px] font-semibold text-foreground tabular">
                      {row.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {/* Axis labels row below chart */}
      <div className="flex items-center justify-between text-[10px] text-quiet">
        {altS.length > 0 ? (
          <span>Left axis: {altS.map((s) => s.label).join(", ")}</span>
        ) : (
          <span />
        )}
        {priceS.length > 0 ? (
          <span>Right axis: {priceS.map((s) => s.label).join(", ")}</span>
        ) : null}
      </div>
    </div>
  );
}
