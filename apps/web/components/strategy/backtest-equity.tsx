"use client";

// module: BacktestEquity — the per-strategy backtest equity panel.
// Fetches GET /explorer/{versionId} → ExplorerDetailResponse and renders:
//   • a two-line SVG overlay of gross vs net equity (the gap = cost drag)
//   • a drawdown band derived from stats.max_dd (peak-to-trough shaded floor)
//   • a compact stats row: max_dd / net return / num_trades / DSR
//
// HONESTY: every number is bound to a REAL field from ExplorerDetailResponse (generated types only,
// never hand-typed). When equity_curve has < 2 points the chart renders its honest empty state.
// While loading, a skeleton placeholder; on engine error, an explicit "—" note.
// GENERATED TYPES ONLY — never hand-type API models (packages/contracts-ts).

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { CellCurveResponse, ExplorerDetailResponse, LabSymbolRow } from "@cosmu/contracts-ts";
import { engineGetJson } from "@/lib/engine";
import { formatOosWindow } from "./strategy-sheet-utils";
import { cn, formatUsd } from "@/lib/utils";

// ── Two-line SVG chart: gross (faint, var(--muted)) + net (var(--up)/var(--down)) + optional drawdown band ──
// Built inline to support two series; the single-series EquityChart primitive can't overlay two lines
// with separate fills + a drawdown band without deep refactoring (the ref-based crosshair wires to
// a single value array). This component is standalone and does not conflict with EquityChart.

type TwoLineChartProps = {
  // `gross` is optional: the executions-based curve overlays gross (pre-cost) + net, but the PER-CELL backtest
  // curve has only a net-of-fee series (we never persisted a gross/pre-cost reconstruction), so it renders the
  // net line alone. Omit / pass [] for the net-only render.
  gross?: number[];
  net: number[];
  labels?: string[];
  height?: number;
  maxDdFrac?: number | null; // max drawdown as 0..1 fraction (e.g. 0.12 for 12%)
  valueFormat?: (i: number, series: "gross" | "net") => string;
  onScrub?: (i: number) => void;
};

function TwoLineChart({
  gross = [],
  net,
  labels,
  height = 150,
  maxDdFrac,
  valueFormat,
  onScrub
}: TwoLineChartProps) {
  const gid = useId().replace(/:/g, "");
  const wrapRef = useRef<HTMLDivElement>(null);
  const lineRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  const hasGross = gross.length > 0;
  const n = hasGross ? Math.min(gross.length, net.length) : net.length;
  const netColor = n > 1 && net[n - 1] >= net[0] ? "var(--up)" : "var(--down)";
  const grossColor = "var(--muted)";

  const geom = useMemo(() => {
    if (n < 2) return null;
    const W = 1000;
    const H = height;
    const PT = 14;
    const PB = 14;
    const allVals = hasGross ? [...gross.slice(0, n), ...net.slice(0, n)] : [...net.slice(0, n)];
    const mn = Math.min(...allVals);
    const mx = Math.max(...allVals);
    const rng = mx - mn || Math.abs(mx) * 0.01 || 1;
    const lo = mn - rng * 0.3;
    const hi = mx + rng * 0.3;
    const R = hi - lo;
    const X = (i: number) => (i / (n - 1)) * W;
    const Y = (v: number) => PT + (H - PT - PB) * (1 - (v - lo) / R);
    const grossLine = hasGross ? gross.slice(0, n).map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ") : "";
    const netPts = net.slice(0, n).map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`);
    const netLine = netPts.join(" ");
    // Net area fill (under the net line)
    const netArea = `M0,${Y(net[0]).toFixed(1)} L${netPts.join(" L")} L${W},${H} L0,${H}Z`;
    const grids = [0.25, 0.5, 0.75].map((g) => (PT + (H - PT - PB) * g).toFixed(1));

    // Drawdown band: a shaded strip from the BOTTOM of the chart up to the max drawdown floor.
    // The band height = max_dd fraction × the chart's usable area height.
    let ddBandY: number | null = null;
    if (typeof maxDdFrac === "number" && maxDdFrac > 0 && maxDdFrac <= 1) {
      // Y-coordinate of the band TOP (band extends from ddBandY to H)
      // We shade the bottom max_dd fraction of the chart area as a visual "worst-case drop" guide.
      const usable = H - PT - PB;
      ddBandY = PT + usable * (1 - maxDdFrac);
    }

    return { W, H, X, Y, grossLine, netLine, netArea, grids, ddBandY, netColor, hasGross };
  }, [gross, net, n, height, maxDdFrac, netColor, hasGross]);

  if (!geom) {
    return (
      <div className="eq-empty">
        No backtest curve — equity_curve has fewer than 2 points for this version.
      </div>
    );
  }

  function move(ev: React.MouseEvent<SVGSVGElement>) {
    if (!geom) return;
    const wrap = wrapRef.current;
    const xl = lineRef.current;
    const xd = dotRef.current;
    const xt = tipRef.current;
    if (!wrap || !xl || !xd || !xt) return;
    const r = ev.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    const idx = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
    const xp = (idx / (n - 1)) * 100;
    const yp = (geom.Y(net[idx]) / geom.H) * 100;
    wrap.classList.add("on");
    xl.style.left = `${xp}%`;
    xd.style.left = `${xp}%`;
    xd.style.top = `${yp}%`;
    xd.style.background = geom.netColor;
    const tx = Math.max(6, Math.min(xp, 94));
    const above = yp > 30;
    xt.style.left = `${tx}%`;
    xt.style.top = `calc(${yp}% ${above ? "- 10px" : "+ 14px"})`;
    xt.style.transform = `translate(-50%,${above ? "-100%" : "0"})`;
    const tvEl = xt.querySelector(".tv");
    const tdEl = xt.querySelector(".td");
    if (tvEl)
      tvEl.textContent = valueFormat
        ? valueFormat(idx, "net")
        : hasGross
          ? `Net ${formatUsd(net[idx], 2)} / Gross ${formatUsd(gross[idx], 2)}`
          : `Net ${formatUsd(net[idx], 2)}`;
    if (tdEl) tdEl.textContent = labels?.[idx] ?? "";
    onScrub?.(idx);
  }

  function leave() {
    wrapRef.current?.classList.remove("on");
    onScrub?.(-1);
  }

  return (
    <div className="eqwrap sheet-eq" ref={wrapRef} style={{ height: geom.H }}>
      <svg
        viewBox={`0 0 ${geom.W} ${geom.H}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: geom.H, display: "block" }}
        onMouseMove={move}
        onMouseLeave={leave}
      >
        <defs>
          <linearGradient id={`bt-ng-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={geom.netColor} stopOpacity="0.18" />
            <stop offset="100%" stopColor={geom.netColor} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {geom.grids.map((gy) => (
          <line key={gy} x1="0" y1={gy} x2={geom.W} y2={gy} stroke="var(--hairline)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        ))}

        {/* Drawdown band — shaded floor showing max drawdown depth */}
        {geom.ddBandY !== null ? (
          <rect
            x="0"
            y={geom.ddBandY}
            width={geom.W}
            height={geom.H - geom.ddBandY}
            fill="var(--down)"
            fillOpacity="0.06"
          />
        ) : null}

        {/* Net area fill */}
        <path d={geom.netArea} fill={`url(#bt-ng-${gid})`} />

        {/* Gross line (faint — the "before costs" reference). Omitted for the net-only per-cell curve. */}
        {geom.hasGross ? (
          <polyline
            points={geom.grossLine}
            fill="none"
            stroke={grossColor}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}

        {/* Net line (bold — the real after-costs equity) */}
        <polyline
          points={geom.netLine}
          fill="none"
          stroke={geom.netColor}
          strokeWidth="2"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <div className="xh-line" ref={lineRef} />
      <div className="xh-dot" ref={dotRef} />
      <div className="xh-tip" ref={tipRef}>
        <div className="tv" />
        <div className="td" />
      </div>
    </div>
  );
}

// ── Stats bar — key metrics from ExplorerStats, displayed compactly below the chart ──
function StatRow({ label, value, tone }: { label: string; value: string; tone?: "up" | "dn" }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 64 }}>
      <span style={{ fontSize: 9.5, color: "var(--quiet)", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</span>
      <span className={cn("tab", tone)} style={{ fontSize: 13, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

// ── Legend — gross vs net line legend. `showGross` is false for the net-only per-cell curve. ──
function Legend({ netColor, showGross = true }: { netColor: string; showGross?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 6 }}>
      <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
        <svg width="22" height="8" style={{ flexShrink: 0 }}>
          <line x1="0" y1="4" x2="22" y2="4" stroke={netColor} strokeWidth="2" />
        </svg>
        <span style={{ fontSize: 10, color: "var(--quiet)" }}>Net (after costs)</span>
      </div>
      {showGross ? (
        <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
          <svg width="22" height="8" style={{ flexShrink: 0 }}>
            <line x1="0" y1="4" x2="22" y2="4" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="4 3" />
          </svg>
          <span style={{ fontSize: 10, color: "var(--quiet)" }}>Gross (pre-cost)</span>
        </div>
      ) : null}
    </div>
  );
}

// ── BacktestEquity — the backtest equity body rendered in the strategy sheet ──
// A pure dispatcher (NO hooks here, so the cell/version branch can't reorder hooks): when the sheet is focused
// on ONE (algo × asset × venue) cell, render THAT cell's standalone net-of-fee backtest curve
// (CellBacktestEquity → GET /strategies/{id}/cell-curve); otherwise the version-level /explorer curve
// (VersionBacktestEquity). The /explorer curve is built from executions (fills), so a backtest-only cell shows
// nothing — the per-cell curve is the stored bar-by-bar net equity the cell's metrics scored on. Paper/Live
// tracks keep the executions-based curve (rendered by PhasedEquity, not this component).
// `embedded`: render only the inner body (chart + legend + stats), with NO outer `.psec` box or `.eq-head`
// title — used inside the shared EquityPanel, which owns the single box + phase toggle.
export function BacktestEquity({
  versionId,
  height = 140,
  embedded = false,
  cell = null
}: {
  versionId: string;
  height?: number;
  embedded?: boolean;
  cell?: LabSymbolRow | null;
}) {
  return cell ? (
    <CellBacktestEquity versionId={versionId} cell={cell} height={height} embedded={embedded} />
  ) : (
    <VersionBacktestEquity versionId={versionId} height={height} embedded={embedded} />
  );
}

// ── VersionBacktestEquity — the version-level /explorer curve (gross + net from stored fills). ──
// Fetches GET /explorer/{versionId} lazily on mount; shows a skeleton while loading.
function VersionBacktestEquity({ versionId, height = 140, embedded = false }: { versionId: string; height?: number; embedded?: boolean }) {
  const [data, setData] = useState<ExplorerDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [hover, setHover] = useState(-1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    engineGetJson<ExplorerDetailResponse>(`/explorer/${versionId}`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [versionId]);

  if (loading) {
    const skel = <div className="skel" style={{ height, borderRadius: "var(--r-sm)" }} />;
    if (embedded) return skel;
    return (
      <div className="psec">
        <div className="eq-head">
          <span className="eq-title-txt">Backtest equity</span>
        </div>
        {skel}
      </div>
    );
  }

  if (error || !data) {
    const note = <div className="eq-empty">Engine not reachable — backtest curve unavailable.</div>;
    if (embedded) return note;
    return (
      <div className="psec">
        <div className="eq-head">
          <span className="eq-title-txt">Backtest equity</span>
        </div>
        {note}
      </div>
    );
  }

  const curve = data.equity_curve ?? [];
  const gross = curve.map((p) => p.gross);
  const net = curve.map((p) => p.net);
  const labels = curve.map((p) => {
    const d = new Date(p.ts);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
  });

  const stats = data.stats;
  const n = Math.min(gross.length, net.length);
  const netColor = n > 1 && net[n - 1] >= net[0] ? "var(--up)" : "var(--down)";

  // Headline value: net equity at the hovered point, or end-point, or "—".
  const hoverVal = hover >= 0 && hover < net.length ? `Net ${formatUsd(net[hover], 2)} · Gross ${formatUsd(gross[hover], 2)}` : null;
  const endVal = net.length > 0 ? `Net ${formatUsd(net[net.length - 1], 2)} · Gross ${formatUsd(gross[gross.length - 1], 2)}` : null;
  const headlineText = hoverVal ?? endVal;

  // Stats from explorer stats (ExplorerStats contract — generated types only)
  const maxDdFrac = typeof stats.max_dd === "number" && stats.max_dd !== null ? stats.max_dd : null;
  const maxDdPct = maxDdFrac !== null ? `${(maxDdFrac * 100).toFixed(1)}%` : "—";
  const netRetPct =
    typeof stats.net_return_pct === "number" && stats.net_return_pct !== null
      ? `${stats.net_return_pct >= 0 ? "+" : ""}${stats.net_return_pct.toFixed(1)}%`
      : "—";
  const grossRetPct =
    typeof stats.gross_return_pct === "number" && stats.gross_return_pct !== null
      ? `${stats.gross_return_pct >= 0 ? "+" : ""}${stats.gross_return_pct.toFixed(1)}%`
      : "—";
  const dsr =
    typeof stats.deflated_sharpe === "number" && stats.deflated_sharpe !== null
      ? stats.deflated_sharpe.toFixed(2)
      : "—";
  const trades =
    typeof stats.num_trades === "number" && stats.num_trades !== null ? String(stats.num_trades) : "—";
  const costRatioPct =
    typeof stats.cost_ratio === "number" && stats.cost_ratio !== null
      ? `${(stats.cost_ratio * 100).toFixed(1)}%`
      : null;

  const netTone: "up" | "dn" | undefined =
    typeof stats.net_return_pct === "number"
      ? stats.net_return_pct >= 0
        ? "up"
        : "dn"
      : undefined;
  const ddTone: "dn" | undefined = maxDdFrac !== null && maxDdFrac > 0.2 ? "dn" : undefined;

  const body = (
    <>
      <TwoLineChart
        gross={gross}
        net={net}
        labels={labels}
        height={height}
        maxDdFrac={maxDdFrac}
        onScrub={setHover}
      />

      <Legend netColor={netColor} />

      {/* Drawdown band caption */}
      {maxDdFrac !== null ? (
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: "var(--down)", opacity: 0.22, flexShrink: 0 }} />
          <span style={{ fontSize: 10, color: "var(--quiet)" }}>
            Max drawdown band: {maxDdPct} peak-to-trough
          </span>
        </div>
      ) : null}

      {/* Stats row */}
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 12 }}>
        <StatRow label="Net return" value={netRetPct} tone={netTone} />
        <StatRow label="Gross return" value={grossRetPct} />
        {costRatioPct ? (
          <StatRow label="Cost drag" value={costRatioPct} />
        ) : null}
        <StatRow label="Max drawdown" value={maxDdPct} tone={ddTone} />
        <StatRow label="Trades" value={trades} />
        <StatRow label="DSR" value={dsr} tone={typeof stats.deflated_sharpe === "number" && stats.deflated_sharpe >= 0.95 ? "up" : undefined} />
      </div>
    </>
  );

  // Embedded: the EquityPanel owns the box + header (title + phase toggle); we render only the body.
  // The hovered Net/Gross value still surfaces via the in-chart crosshair tooltip.
  if (embedded) return body;

  return (
    <div className="psec">
      <div className="eq-head">
        <span className="eq-title-txt">
          {headlineText ? `Backtest equity · ${headlineText}` : "Backtest equity"}
        </span>
      </div>
      {body}
    </div>
  );
}

// ── CellBacktestEquity — the PER-CELL standalone net-of-fee backtest curve. ──
// Fetches GET /strategies/{versionId}/cell-curve?symbol=&venue= (the cumulated bar-by-bar net equity this exact
// (symbol, venue) cell's metrics scored on — stored at screen time, NEVER re-run, NEVER the pooled basket). There
// is no persisted gross/pre-cost series per cell, so this renders the NET line alone. The stats below bind to the
// focused cell's OWN standalone fields (return_pct / max_drawdown / trades / sharpe) — the SAME granular truth the
// rest of the sheet uses — never the pooled backtest aggregate.
function CellBacktestEquity({
  versionId,
  cell,
  height = 140,
  embedded = false
}: {
  versionId: string;
  cell: LabSymbolRow;
  height?: number;
  embedded?: boolean;
}) {
  const [data, setData] = useState<CellCurveResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [hover, setHover] = useState(-1);

  // venue: "" addresses the NULL-venue cell explicitly (matches the engine's /cell-curve selector).
  const venueParam = cell.venue_id ?? "";
  const path = `/strategies/${versionId}/cell-curve?symbol=${encodeURIComponent(cell.symbol)}&venue=${encodeURIComponent(venueParam)}`;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    engineGetJson<CellCurveResponse>(path)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const titleBox = (inner: React.ReactNode) =>
    embedded ? (
      inner
    ) : (
      <div className="psec">
        <div className="eq-head">
          <span className="eq-title-txt">Backtest equity</span>
        </div>
        {inner}
      </div>
    );

  if (loading) {
    return titleBox(<div className="skel" style={{ height, borderRadius: "var(--r-sm)" }} />);
  }
  if (error) {
    return titleBox(<div className="eq-empty">Engine not reachable — backtest curve unavailable.</div>);
  }
  if (!data || !data.available || data.points.length < 2) {
    // Honest per-cell empty state: forward-only — the curve accrues once this cell is (re-)screened + persisted.
    return titleBox(
      <div className="eq-empty">
        No backtest curve yet for this {cell.symbol}
        {cell.venue_id ? ` · ${cell.venue_id}` : ""} cell — it accrues as the combo is re-screened.
      </div>
    );
  }

  const net = data.points.map((p) => p.net);
  const labels = data.points.map((p) => {
    const d = new Date(p.ts);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "2-digit" });
  });
  const n = net.length;
  const netColor = n > 1 && net[n - 1] >= net[0] ? "var(--up)" : "var(--down)";

  // Stats from the focused cell's OWN standalone fields (return_pct / max_drawdown are FRACTIONS).
  const maxDdFrac = typeof cell.max_drawdown === "number" ? cell.max_drawdown : null;
  const maxDdPct = maxDdFrac !== null ? `${(maxDdFrac * 100).toFixed(1)}%` : "—";
  const netRetPct =
    typeof cell.return_pct === "number"
      ? `${cell.return_pct >= 0 ? "+" : ""}${(cell.return_pct * 100).toFixed(1)}%`
      : "—";
  const annRetPct =
    typeof cell.return_pct_annualized === "number" && cell.return_pct_annualized !== null
      ? `${cell.return_pct_annualized >= 0 ? "+" : ""}${(cell.return_pct_annualized * 100).toFixed(1)}%`
      : null;
  const sharpe = typeof cell.sharpe === "number" ? cell.sharpe.toFixed(2) : "—";
  const trades = typeof cell.trades === "number" ? String(cell.trades) : "—";
  const netTone: "up" | "dn" | undefined =
    typeof cell.return_pct === "number" ? (cell.return_pct >= 0 ? "up" : "dn") : undefined;
  const ddTone: "dn" | undefined = maxDdFrac !== null && maxDdFrac > 0.2 ? "dn" : undefined;

  const hoverVal = hover >= 0 && hover < net.length ? `Net ${formatUsd(net[hover], 2)}` : null;
  const endVal = net.length > 0 ? `Net ${formatUsd(net[net.length - 1], 2)}` : null;
  const headlineText = hoverVal ?? endVal;

  const body = (
    <>
      <TwoLineChart
        net={net}
        labels={labels}
        height={height}
        maxDdFrac={maxDdFrac}
        valueFormat={(i) => `Net ${formatUsd(net[i], 2)}`}
        onScrub={setHover}
      />

      <Legend netColor={netColor} showGross={false} />

      {maxDdFrac !== null ? (
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: "var(--down)", opacity: 0.22, flexShrink: 0 }} />
          <span style={{ fontSize: 10, color: "var(--quiet)" }}>Max drawdown band: {maxDdPct} peak-to-trough</span>
        </div>
      ) : null}

      <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 12 }}>
        <StatRow label="Net return" value={netRetPct} tone={netTone} />
        {annRetPct ? <StatRow label="Net return / yr" value={annRetPct} tone={netTone} /> : null}
        <StatRow label="Max drawdown" value={maxDdPct} tone={ddTone} />
        <StatRow label="Trades" value={trades} />
        <StatRow label="Sharpe" value={sharpe} />
        <StatRow label="OOS window" value={formatOosWindow(cell.oos_window_days) ?? "—"} />
      </div>
    </>
  );

  if (embedded) return body;

  return (
    <div className="psec">
      <div className="eq-head">
        <span className="eq-title-txt">
          {headlineText ? `Backtest equity · ${headlineText}` : "Backtest equity"}
        </span>
      </div>
      {body}
    </div>
  );
}
