"use client";

// Reusable equity / spend curve (Iris Bento `.eqwrap`). A faithful React port of the reference
// mockup's hand-rolled SVG chart (`curveInto`/`chartSVG`): an area + line with three gridlines and an
// interactive crosshair (vertical line, dot, value tooltip) on hover. Theme-aware via CSS vars; no
// chart library. Used by Paper, Live, Costs and the strategy sheet.
//
// HONESTY: pass only REAL series. When `values` is empty it renders an honest "no curve yet" empty
// state — never a fabricated line. Callers also drive the headline value via the optional `onScrub`.

import { useId, useMemo, useRef } from "react";

export type EquityChartProps = {
  values: number[];
  labels?: string[];
  /** Line/fill colour (any CSS colour incl. var(--…)). Omit to derive up/down from the series direction. */
  color?: string;
  /** Chart height in px (default 150). */
  height?: number;
  /** Tooltip value text for index i (default "$1,234"). */
  valueFormat?: (i: number) => string;
  /** Min/max axis labels under the chart (first + last label). */
  axis?: boolean;
  /** Called with the hovered index, or -1 on leave — lets a parent mirror the value into a headline. */
  onScrub?: (i: number) => void;
  /** Honest empty-state message when there is no series. */
  emptyHint?: string;
  /** Optional cost-basis / window-start reference: draws a faint dashed line and is folded into the y-domain so
   *  a small move reads relative to invested capital instead of being auto-zoomed into noise. */
  baseline?: number;
};

export function EquityChart({ values, labels, color, height = 150, valueFormat, axis = false, onScrub, emptyHint, baseline }: EquityChartProps) {
  const gid = useId().replace(/:/g, "");
  const wrapRef = useRef<HTMLDivElement>(null);
  const lineRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  const n = values.length;
  const stroke = color ?? (n > 1 && values[n - 1] >= values[0] ? "var(--up)" : "var(--down)");
  const fmt = valueFormat ?? ((i: number) => `$${Math.round(values[i]).toLocaleString("en-US")}`);
  const fmtV = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;

  const geom = useMemo(() => {
    if (n === 0) return null;
    // Defensive parity with Sparkline: derive the domain from the FINITE values only, so a stray non-finite point
    // (should never happen — callers pass real series) breaks just its own line segment instead of NaN-ing the
    // whole chart into a blank box; an all-non-finite series falls through to the honest empty state below.
    const finite = values.filter((v) => Number.isFinite(v));
    if (finite.length === 0) return null;
    const W = 1000;
    const H = height;
    const PT = 14;
    const PB = 14;
    // Frame the y-domain around the data AND the baseline (cost basis), so a small +/- move reads relative to
    // what was invested rather than being auto-zoomed into noise. With no baseline this is the data min/max as before.
    const mn = Math.min(...finite, baseline ?? Infinity);
    const mx = Math.max(...finite, baseline ?? -Infinity);
    const rng = mx - mn || Math.abs(mx) * 0.01 || 1;
    const lo = mn - rng * 0.3;
    const hi = mx + rng * 0.3;
    const R = hi - lo;
    const X = (i: number) => (n > 1 ? (i / (n - 1)) * W : 0);
    const Y = (v: number) => PT + (H - PT - PB) * (1 - (v - lo) / R);
    const pts = values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`);
    const line = pts.join(" ");
    const area = `M0,${Y(values[0]).toFixed(1)} L${pts.join(" L")} L${W},${H} L0,${H}Z`;
    const grids = [0.25, 0.5, 0.75].map((g) => (PT + (H - PT - PB) * g).toFixed(1));
    const baseTopPct = baseline != null ? (Y(baseline) / H) * 100 : null;
    return { W, H, X, Y, line, area, grids, baseTopPct };
  }, [values, n, height, baseline]);

  if (!geom) {
    return (
      <div className="eq-empty">{emptyHint ?? "No curve yet — this fills in once the engine reports a real series."}</div>
    );
  }

  function move(ev: React.MouseEvent<SVGSVGElement>) {
    if (!geom) return;
    const svg = ev.currentTarget;
    const wrap = wrapRef.current;
    const xl = lineRef.current;
    const xd = dotRef.current;
    const xt = tipRef.current;
    if (!wrap || !xl || !xd || !xt) return;
    const r = svg.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    const idx = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
    const xp = (n > 1 ? idx / (n - 1) : 0) * 100;
    const yp = (geom.Y(values[idx]) / geom.H) * 100;
    wrap.classList.add("on");
    xl.style.left = `${xp}%`;
    xd.style.left = `${xp}%`;
    xd.style.top = `${yp}%`;
    xd.style.background = stroke;
    const tx = Math.max(6, Math.min(xp, 94));
    const above = yp > 30;
    xt.style.left = `${tx}%`;
    xt.style.top = `calc(${yp}% ${above ? "- 10px" : "+ 14px"})`;
    xt.style.transform = `translate(-50%,${above ? "-100%" : "0"})`;
    const tv = xt.querySelector(".tv");
    const td = xt.querySelector(".td");
    if (tv) tv.textContent = fmt(idx);
    if (td) td.textContent = labels?.[idx] ?? "";
    onScrub?.(idx);
  }

  function leave() {
    wrapRef.current?.classList.remove("on");
    onScrub?.(-1);
  }

  return (
    <>
      <div className="eqwrap sheet-eq" ref={wrapRef} style={{ height: geom.H }}>
        <svg viewBox={`0 0 ${geom.W} ${geom.H}`} preserveAspectRatio="none" style={{ width: "100%", height: geom.H, display: "block" }} onMouseMove={move} onMouseLeave={leave}>
          <defs>
            <linearGradient id={`eg-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>
          {geom.grids.map((gy) => (
            <line key={gy} x1="0" y1={gy} x2={geom.W} y2={gy} stroke="var(--hairline)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          <path d={geom.area} fill={`url(#eg-${gid})`} />
          <polyline points={geom.line} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {geom.baseTopPct != null ? (
          <div className="eq-base" style={{ top: `${geom.baseTopPct}%` }}>
            <span className="eq-base-lbl mono">{fmtV(baseline!)}</span>
          </div>
        ) : null}
        <div className="xh-line" ref={lineRef} />
        <div className="xh-dot" ref={dotRef} />
        <div className="xh-tip" ref={tipRef}>
          <div className="tv" />
          <div className="td" />
        </div>
      </div>
      {axis ? (
        <div className="eq-axis">
          <span>{labels?.[0] ?? ""}</span>
          <span>{labels?.[labels.length - 1] ?? ""}</span>
        </div>
      ) : null}
    </>
  );
}
