"use client";

// module: the unified Strategies SCREENER (v18 "Iris Bento", docs/PRODUCT.md Epic B). A faithful port of
// the reference mockup's `renderScreener` mechanics into React, bound to REAL leaderboard rows. Every
// Version runs on its own standalone track and is ranked by RISK-ADJUSTED % (deflated OOS Sharpe / "DSR"),
// with net dollars and % shown alongside.
//
// MECHANICS reproduced verbatim from the mockup:
//   • filter chips  (All / Live / Paper / Killed / Queued) — bento `.chip-row` / `.chip` / `.chip-dot`.
//   • text search   (`.search-input`) over name + features + edge.
//   • sortable headers with the `.sort-ind` ▲/▼ indicator; click cycles dir then back to the DSR default.
//   • column picker (`.col-picker-*`) — toggle columns via `.cp-ind` checkmark, drag-reorder the headers
//     (`draggable` + `.drag-over`), "Reset to default view". Venue / Fees / Origin are OFF by default.
//   • lifecycle `.glyph` dots, the `.dsr-wrap` bar, the `.dd-arc` SVG (LeaderboardRow has NO max-dd, so the
//     DD cell honestly reads "—"), the `.pnl-wrap` two-line P&L.
//   • the whole table scrolls horizontally inside `.screener-wrap`; a colgroup sizes the columns.
//   • row click → opens the right `SidePanel` with the full per-Version sheet (fetched client-side).
//
// HONESTY: every cell renders ONLY a real field; a null money field (value_usd / pnl_usd / pnl_pct) reads
// an explicit "—" in a `.quiet` span, NEVER 0. The leaderboard contract carries no max-drawdown or fee
// field, so "Max DD" and "Fees" honestly read "—" until the engine surfaces them — never a fabricated arc
// or cost.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import type { LeaderboardRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { SidePanel } from "@/components/ui/side-panel";
import { StrategySheet } from "@/components/strategy/strategy-sheet";
import type { Stage } from "@/components/strategy/stage-control";
import { engineFetch, engineGetJson, enginePeek, enginePrefetch } from "@/lib/engine";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { cn, formatUsd, formatVenue, numOrNull, signedUsd } from "@/lib/utils";

// ── Lifecycle mapping — the screener's local lifecycle normalizer (the canonical paper predicate is the
// shared isPaper in lib/utils; this maps the full engine status onto the 5-stage lifecycle/filter lanes). ──
type LifeStatus = "lab" | "screened" | "paper" | "live" | "killed";
// The screener's filter buckets map onto the chips; "lab" reads as Queued, "screened" as Backtest.
type FilterKey = "all" | "live" | "paper" | "backtest" | "killed" | "queued";

// Fill-aware: a paper-ish STATUS only reads "paper" once the track has genuinely traded on paper
// (has_paper_fills). A funded documented arm with zero fills falls to "screened" (Backtest) — so the table
// badge AND the stageOverride it passes to the sheet match the sheet's own fill-based deriveStage, and a
// "Paper" badge can never sit over a strategy whose sheet says "no fills yet".
type RowStage = { status?: string | null; has_paper_fills?: boolean | null };
function lifeStatusOf(row: RowStage | null | undefined): LifeStatus {
  const s = (row?.status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "killed";
  if (s === "live") return "live";
  if (s === "paper" || s === "forward_test" || s === "forward") return row?.has_paper_fills === true ? "paper" : "screened";
  if (s === "screening" || s === "screened" || s === "validating" || s === "optimizing") return "screened";
  return "lab";
}
function filterBucketOf(row: RowStage | null | undefined): FilterKey {
  const life = lifeStatusOf(row);
  if (life === "live") return "live";
  if (life === "paper") return "paper";
  if (life === "killed") return "killed";
  if (life === "screened") return "backtest";
  return "queued"; // lab
}

const STAGE_LABEL: Record<LifeStatus, string> = { lab: "Queued", screened: "Backtest", paper: "Paper", live: "Live", killed: "Killed" };
const STAGE_BADGE_CLASS: Record<LifeStatus, string> = {
  lab: "stage-badge sb-queued",
  screened: "stage-badge sb-backtest-stage",
  paper: "stage-badge sb-paper",
  live: "stage-badge sb-live",
  killed: "stage-badge sb-killed"
};
// Pipeline order for the default "Stage" sort (top-to-bottom by lifecycle maturity).
const STAGE_RANK: Record<LifeStatus, number> = { live: 5, paper: 4, screened: 3, lab: 2, killed: 1 };
// Map the screener's lifecycle onto the sheet's Stage union so the sheet badge matches the table badge.
const LIFE_TO_STAGE: Record<LifeStatus, Stage> = { lab: "queued", screened: "backtest", paper: "paper", live: "live", killed: "killed" };

// The Gate's reference scalars (the green threshold line on the DSR bar; the PBO gold ceiling).
const SHARPE_REF = 2;
const DSR_STRONG = 0.95;
const PBO_CEILING = 0.5;

// ── COLS — each column a lens onto a REAL row field. `sort` makes the header click-to-sort; `defaultOn:
// false` columns start hidden (the v18 opt-ins). `min` feeds the colgroup so columns size correctly. ──
type SortDir = "asc" | "desc";
type ColKey = "name" | "stage" | "life" | "days" | "value" | "pnl" | "pnlpct" | "dsr" | "pbo" | "dd" | "oos" | "venue" | "fees" | "origin";
type ColDef = {
  key: ColKey;
  label: string;
  pickerLabel?: string;
  width: number;
  defaultOn?: boolean;
  // togglable in the picker (name is the identity — never togglable)
  pickable?: boolean;
  sort?: { dir: SortDir; value: (r: LeaderboardRow) => number | string | null };
};

const COLS: ColDef[] = [
  { key: "name", label: "Name", width: 240, sort: { dir: "asc", value: (r) => r.name.toLowerCase() } },
  { key: "stage", label: "Stage", width: 90, pickable: true, sort: { dir: "desc", value: (r) => STAGE_RANK[lifeStatusOf(r)] } },
  { key: "days", label: "Days", width: 42, pickable: true, sort: { dir: "desc", value: (r) => (Number.isFinite(r.paper_age_days) ? r.paper_age_days : null) } },
  { key: "value", label: "Value", width: 72, pickable: true, sort: { dir: "desc", value: (r) => numOrNull(r.value_usd) } },
  { key: "pnl", label: "P&L", width: 66, pickable: true, sort: { dir: "desc", value: (r) => numOrNull(r.pnl_usd) } },
  { key: "pnlpct", label: "P&L %", width: 58, pickable: true, sort: { dir: "desc", value: (r) => numOrNull(r.pnl_pct) } },
  { key: "dsr", label: "DSR", width: 94, pickable: true, sort: { dir: "desc", value: (r) => (Number.isFinite(r.deflated_sharpe) ? r.deflated_sharpe : null) } },
  { key: "pbo", label: "PBO", width: 64, pickable: true, sort: { dir: "asc", value: (r) => (Number.isFinite(r.pbo) ? r.pbo : null) } },
  { key: "dd", label: "Max DD", width: 80, defaultOn: false, pickable: true },
  { key: "oos", label: "OOS", width: 70, pickable: true, sort: { dir: "desc", value: (r) => (Number.isFinite(r.track_return_pct) ? r.track_return_pct : null) } },
  { key: "venue", label: "Venue", width: 72, defaultOn: false, pickable: true, sort: { dir: "asc", value: (r) => r.venue } },
  { key: "fees", label: "Fees", pickerLabel: "Fees paid", width: 74, defaultOn: false, pickable: true },
  { key: "origin", label: "Origin", width: 82, defaultOn: false, pickable: true, sort: { dir: "asc", value: (r) => r.origin } }
];

const DEFAULT_ORDER: ColKey[] = COLS.map((c) => c.key);
const DEFAULT_VISIBLE: Record<ColKey, boolean> = COLS.reduce(
  (acc, c) => ({ ...acc, [c.key]: c.defaultOn !== false }),
  {} as Record<ColKey, boolean>
);
const COL_BY_KEY: Record<ColKey, ColDef> = COLS.reduce((acc, c) => ({ ...acc, [c.key]: c }), {} as Record<ColKey, ColDef>);

// Compact OOS window from days: "2.4y" / "18mo" / "9mo". null/absent → "".
function formatWindow(days: number | null | undefined): string {
  if (typeof days !== "number" || !Number.isFinite(days) || days <= 0) return "";
  if (days >= 365) return `${(days / 365).toFixed(1)}y`;
  const months = Math.round(days / 30);
  if (months >= 1) return `${months}mo`;
  return `${Math.round(days)}d`;
}

// Annualized return (CAGR) from a TOTAL return % over a window in days — the comparable number across
// strategies with different test lengths. null when the window is unknown or the inputs are degenerate
// (total <= -100% would imply a wipeout; we don't annualize that). Years = days/365.25.
function annualizedPct(totalPct: number | null | undefined, windowDays: number | null | undefined): number | null {
  if (typeof totalPct !== "number" || !Number.isFinite(totalPct)) return null;
  if (typeof windowDays !== "number" || !Number.isFinite(windowDays) || windowDays <= 0) return null;
  const years = windowDays / 365.25;
  if (years <= 0 || totalPct <= -100) return null;
  const cagr = Math.pow(1 + totalPct / 100, 1 / years) - 1;
  return Number.isFinite(cagr) ? cagr * 100 : null;
}

export function StrategiesTable({ rows, ribbon }: { rows: LeaderboardRow[]; ribbon?: ReactNode }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [order, setOrder] = useState<ColKey[]>([...DEFAULT_ORDER]);
  const [visible, setVisible] = useState<Record<ColKey, boolean>>({ ...DEFAULT_VISIBLE });
  const [showPicker, setShowPicker] = useState(false);
  const [sort, setSort] = useState<{ key: ColKey; dir: SortDir }>({ key: "stage", dir: "desc" });
  // Initial selection from ?v=<version_id> so a strategy link from a dashboard table opens its sheet here.
  const searchParams = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("v"));
  const dragKey = useRef<ColKey | null>(null);

  // Close the column picker on an outside click (the v18 menu behaviour).
  const pickerWrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showPicker) return;
    function onDoc(e: MouseEvent) {
      if (pickerWrapRef.current && !pickerWrapRef.current.contains(e.target as Node)) setShowPicker(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showPicker]);

  // ── search → filter → sort ──
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const searched = rows.filter((r) => {
      if (q && !(r.name.toLowerCase().includes(q) || r.features.some((f) => f.toLowerCase().includes(q)) || r.edge_type.toLowerCase().includes(q))) {
        return false;
      }
      if (filter === "all") return true;
      return filterBucketOf(r) === filter;
    });
    const col = COL_BY_KEY[sort.key];
    const getter = col?.sort?.value;
    const sign = sort.dir === "asc" ? 1 : -1;
    return searched.slice().sort((a, b) => {
      if (getter) {
        const va = getter(a);
        const vb = getter(b);
        const an = va === null || va === undefined;
        const bn = vb === null || vb === undefined;
        if (an && bn) return tieByDsr(a, b);
        if (an) return 1;
        if (bn) return -1;
        if (typeof va === "string" || typeof vb === "string") {
          const d = String(va).localeCompare(String(vb));
          if (d !== 0) return sign * d;
          return tieByDsr(a, b);
        }
        const d = (va as number) - (vb as number);
        if (d !== 0) return sign * d;
      }
      return tieByDsr(a, b);
    });
  }, [rows, query, filter, sort]);

  const visibleCols = useMemo(() => order.map((k) => COL_BY_KEY[k]).filter((c) => visible[c.key]), [order, visible]);
  const minWidth = useMemo(() => visibleCols.reduce((sum, c) => sum + c.width, 0), [visibleCols]);

  // INSTANT SHEETS: warm the detail cache for the top visible rows on mount (and whenever the sort/filter
  // reshuffles them), so the FIRST click opens immediately instead of paying the ~2s cold engine round-trip.
  // enginePrefetch dedups + caches; capped at 12 so we never fan dozens of reads. Hover-prefetch + the cache
  // cover everything below the fold.
  useEffect(() => {
    for (const r of filtered.slice(0, 12)) enginePrefetch(`/strategies/${r.version_id}`);
  }, [filtered]);

  // Cycle a sortable header: inactive → natural dir → flip → back to the house default (DSR-ranked Stage).
  const toggleSort = useCallback((col: ColDef) => {
    if (!col.sort) return;
    setSort((prev) => {
      if (prev.key !== col.key) return { key: col.key, dir: col.sort!.dir };
      const flipped: SortDir = prev.dir === "asc" ? "desc" : "asc";
      if (flipped === col.sort!.dir) return { key: "stage", dir: "desc" };
      return { key: col.key, dir: flipped };
    });
  }, []);

  function toggleCol(key: ColKey) {
    setVisible((prev) => ({ ...prev, [key]: !prev[key] }));
  }
  function resetCols() {
    setOrder([...DEFAULT_ORDER]);
    setVisible({ ...DEFAULT_VISIBLE });
  }

  // ── header drag-reorder ──
  const [dragOver, setDragOver] = useState<ColKey | null>(null);
  function onDrop(targetKey: ColKey) {
    const from = dragKey.current;
    setDragOver(null);
    if (!from || from === targetKey) return;
    setOrder((prev) => {
      const next = [...prev];
      const fi = next.indexOf(from);
      const ti = next.indexOf(targetKey);
      if (fi < 0 || ti < 0) return prev;
      next.splice(ti, 0, next.splice(fi, 1)[0]);
      return next;
    });
    dragKey.current = null;
  }

  return (
    <>
      {/* ── toolbar controls (the left/right of the page Toolbar are passed by the page; this is the
            screener's own filter row used inside the table cell). ── */}
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <span className="page-title">Strategies</span>
        <div className="chip-row" id="filter-chips">
          <FilterChip label="All" active={filter === "all"} onClick={() => setFilter("all")} />
          <FilterChip label="Live" dot="var(--down)" active={filter === "live"} onClick={() => setFilter("live")} />
          <FilterChip label="Paper" dot="var(--iris)" active={filter === "paper"} onClick={() => setFilter("paper")} />
          <FilterChip label="Backtest" dot="var(--info)" active={filter === "backtest"} onClick={() => setFilter("backtest")} />
          <FilterChip label="Queued" active={filter === "queued"} onClick={() => setFilter("queued")} />
          <FilterChip label="Killed" active={filter === "killed"} onClick={() => setFilter("killed")} />
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
        <input
          className="search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search strategies…"
          aria-label="Search strategies"
        />
        <div className="col-picker-wrap" ref={pickerWrapRef}>
          <button type="button" className="btn-col-picker" onClick={() => setShowPicker((v) => !v)} aria-expanded={showPicker}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <line x1="1" y1="3" x2="11" y2="3" />
              <line x1="1" y1="6" x2="11" y2="6" />
              <line x1="1" y1="9" x2="11" y2="9" />
            </svg>
            Columns
          </button>
          <div className={cn("col-picker-menu cp-1", showPicker && "open")} id="col-picker-menu">
            <div className="cp-head">
              Show columns <span className="cp-hint">click a row</span>
            </div>
            {COLS.filter((c) => c.pickable).map((c, i) => {
              // a divider before the opt-in (default-off) group, matching the mockup
              const isFirstOptIn = c.defaultOn === false && COLS.filter((x) => x.pickable).findIndex((x) => x.defaultOn === false) === i;
              return (
                <div key={c.key}>
                  {isFirstOptIn ? <div className="col-picker-divider" /> : null}
                  <div className={cn("col-picker-item", visible[c.key] && "on")} onClick={() => toggleCol(c.key)}>
                    <span className="cp-ind" />
                    <span className="cp-label">{c.pickerLabel ?? c.label}</span>
                  </div>
                </div>
              );
            })}
            <div className="col-picker-divider" />
            <button type="button" className="cp-reset" onClick={resetCols}>
              Reset to default view
            </button>
          </div>
        </div>
        <ThemeToggle />
        </div>
      </div>

      {/* The live money-split ribbon sits below the toolbar (v18 order). */}
      {ribbon}

      {/* ── ranked screener — horizontal scroll on overflow ── */}
      <div className="screener-wrap">
        {filtered.length === 0 ? (
          <p className="quiet" style={{ fontSize: 12, padding: "24px 4px", textAlign: "center" }}>No versions match these filters.</p>
        ) : (
          <table className="screener-table" style={{ minWidth }}>
            <colgroup>
              {visibleCols.map((c) => (
                <col key={c.key} style={{ width: c.width }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {visibleCols.map((c) => {
                  const active = sort.key === c.key;
                  return (
                    <th
                      key={c.key}
                      draggable
                      onDragStart={() => (dragKey.current = c.key)}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragOver(c.key);
                      }}
                      onDragLeave={() => setDragOver((k) => (k === c.key ? null : k))}
                      onDrop={(e) => {
                        e.preventDefault();
                        onDrop(c.key);
                      }}
                      onDragEnd={() => setDragOver(null)}
                      className={dragOver === c.key ? "drag-over" : undefined}
                      onClick={c.sort ? () => toggleSort(c) : undefined}
                      style={c.sort ? { cursor: "pointer" } : undefined}
                    >
                      <div className="th-inner">
                        {c.label}
                        {c.sort ? <span className={cn("sort-ind", active && (sort.dir === "asc" ? "asc" : "desc"))} /> : null}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const life = lifeStatusOf(row);
                const rowClass = cn(
                  life === "killed" && "row-killed",
                  filterBucketOf(row) === "queued" && life === "lab" && "row-queued",
                  life === "screened" && "row-backtest",
                  row.version_id === selectedId && "sel"
                );
                return (
                  <tr
                    key={row.version_id}
                    className={rowClass || undefined}
                    onClick={() => setSelectedId(row.version_id)}
                    onMouseEnter={() => enginePrefetch(`/strategies/${row.version_id}`)}
                  >
                    {visibleCols.map((c) => (
                      <td key={c.key}>
                        <Cell col={c.key} row={row} life={life} />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <SheetPanel
        id={selectedId}
        stage={selectedId ? LIFE_TO_STAGE[lifeStatusOf(rows.find((r) => r.version_id === selectedId))] : undefined}
        onClose={() => setSelectedId(null)}
      />
    </>
  );
}

function tieByDsr(a: LeaderboardRow, b: LeaderboardRow): number {
  const da = Number.isFinite(a.deflated_sharpe) ? a.deflated_sharpe : -Infinity;
  const db = Number.isFinite(b.deflated_sharpe) ? b.deflated_sharpe : -Infinity;
  return db - da;
}

// ── one screener cell — renders ONLY the real field for `col`; honest "—" for null money / absent field. ──
function Cell({ col, row, life }: { col: ColKey; row: LeaderboardRow; life: LifeStatus }) {
  switch (col) {
    case "name":
      return (
        <div className="cell-name" data-tip={row.name}>
          {row.name}
        </div>
      );
    case "stage":
      return <span className={STAGE_BADGE_CLASS[life]}>{STAGE_LABEL[life]}</span>;
    case "life":
      return <LifecycleGlyph life={life} />;
    case "days": {
      const days = Number.isFinite(row.paper_age_days) ? Math.floor(row.paper_age_days) : 0;
      return days > 0 ? <span className="tab">{days}</span> : <Dash />;
    }
    case "value": {
      const v = numOrNull(row.value_usd);
      return v === null ? <Dash /> : <span className="tab">{formatUsd(v)}</span>;
    }
    case "pnl":
    case "pnlpct": {
      // The two-line P&L wrap (dollars over %). Each of the two columns shows ONE line; honest "—" when null.
      if (col === "pnl") {
        const v = numOrNull(row.pnl_usd);
        if (v === null) return <Dash />;
        return (
          <div className="pnl-wrap">
            <div className={cn("pnl-val tab", v > 0 ? "up" : v < 0 ? "dn" : "")}>{signedUsd(v)}</div>
          </div>
        );
      }
      const v = numOrNull(row.pnl_pct);
      if (v === null) return <Dash />;
      return <span className={cn("tab", v > 0 ? "up" : v < 0 ? "dn" : "")}>{`${v >= 0 ? "+" : ""}${v.toFixed(0)}%`}</span>;
    }
    case "dsr": {
      const dsr = Number.isFinite(row.deflated_sharpe) ? row.deflated_sharpe : null;
      return <DsrBar dsr={dsr} />;
    }
    case "pbo": {
      const pbo = Number.isFinite(row.pbo) ? row.pbo : null;
      if (pbo === null) return <Dash />;
      return <span className={cn("tab", pbo > PBO_CEILING - 0.05 ? "gold" : "")}>{pbo.toFixed(2)}</span>;
    }
    case "dd":
      // LeaderboardRow carries NO max-drawdown — render an honest "—", never a fabricated arc.
      return <Dash />;
    case "oos": {
      const oos = Number.isFinite(row.track_return_pct) ? row.track_return_pct : null;
      if (oos === null) return <Dash />;
      const win = formatWindow(row.oos_window_days);
      // Annualized (CAGR) over the OOS window — the comparable number, since windows differ in length
      // (a +94% over 6yr is ~12%/yr, not 94%). Shown for every strategy incl. Backtest, so the table carries
      // a real return even before any paper P&L. Only when we know the window length; else just the total.
      const ann = annualizedPct(oos, row.oos_window_days);
      return (
        <div style={{ lineHeight: 1.15 }}>
          <span className={cn("tab", oos >= 0 ? "up" : "dn")}>{`${oos >= 0 ? "+" : ""}${oos.toFixed(1)}%`}</span>
          {ann !== null ? (
            <span className="oos-win" data-tip="Annualized (CAGR) over the out-of-sample window — comparable across strategies with different test lengths.">{`${ann >= 0 ? "+" : ""}${ann.toFixed(1)}%/yr`}</span>
          ) : win ? (
            <span className="oos-win">{win}</span>
          ) : null}
        </div>
      );
    }
    case "venue":
      return <span className="muted" style={{ fontSize: 11 }}>{formatVenue(row.venue)}</span>;
    case "fees":
      // No per-Version fee total on the leaderboard contract — honest "—", never a fabricated cost.
      return <Dash />;
    case "origin":
      return <span className="muted" style={{ fontSize: 10.5, textTransform: "capitalize" }}>{row.origin || "—"}</span>;
    default:
      return null;
  }
}

function Dash() {
  return <span className="quiet">—</span>;
}

// ── DSR bar (`.dsr-wrap`) — the bar fills toward a strong (~2) score; the threshold tick marks the 0.95
// live-ready bar. Honest "—" when no DSR. ──
function DsrBar({ dsr }: { dsr: number | null }) {
  if (dsr === null) return <Dash />;
  const pct = Math.min((Math.max(0, dsr) / SHARPE_REF) * 100, 100);
  const col = dsr >= DSR_STRONG ? "var(--up)" : dsr >= 0.8 ? "var(--iris)" : "var(--muted)";
  return (
    <div className="dsr-wrap">
      <div className="dsr-track">
        <div className="dsr-fill" style={{ width: `${pct}%`, background: col }} />
        <div className="dsr-thr" style={{ left: `${(DSR_STRONG / SHARPE_REF) * 100}%` }} />
      </div>
      <span className="dsr-val tab">{dsr.toFixed(2)}</span>
    </div>
  );
}

// ── lifecycle `.glyph` dots — filled = stages reached; the current glows; killed shows a red node. ──
function LifecycleGlyph({ life }: { life: LifeStatus }) {
  // mirrors the mockup's lifGlyph: dot/line classes for a 3-node Backtest → Paper → Live track.
  let nodes: { dot: string; line: string }[];
  if (life === "live") nodes = [{ dot: "done", line: "done" }, { dot: "done", line: "live" }, { dot: "live-c", line: "" }];
  else if (life === "paper") nodes = [{ dot: "done", line: "done" }, { dot: "cur", line: "" }, { dot: "", line: "" }];
  else if (life === "screened") nodes = [{ dot: "cur", line: "" }, { dot: "", line: "" }, { dot: "", line: "" }];
  else if (life === "killed") nodes = [{ dot: "done", line: "done" }, { dot: "dead", line: "" }, { dot: "", line: "" }];
  else nodes = [{ dot: "", line: "" }, { dot: "", line: "" }, { dot: "", line: "" }]; // lab / queued
  return (
    <span className="glyph" aria-label={`lifecycle ${life}`}>
      {nodes.map((n, i) => (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
          <span className={cn("g-dot", n.dot)} />
          {i < nodes.length - 1 ? <span className={cn("g-line", n.line)} /> : null}
        </span>
      ))}
    </span>
  );
}

function FilterChip({ label, dot, active, onClick }: { label: string; dot?: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={cn("chip", active && "active")} onClick={onClick}>
      {dot ? <span className="chip-dot" style={{ background: dot }} /> : label === "All" ? <span className="chip-dot" /> : null}
      {label}
    </button>
  );
}

// ── the right detail sheet — fetches the full Version detail client-side (via the same-origin proxy) and
// renders the SHARED StrategySheet. Honest loading + error states. ──
function SheetPanel({ id, stage, onClose }: { id: string | null; stage?: Stage; onClose: () => void }) {
  const [detail, setDetail] = useState<StrategyDetailResponse | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  useEffect(() => {
    if (!id) {
      setDetail(null);
      setState("idle");
      return;
    }
    // Instant on a cache hit (re-open, or a hover-prefetch already landed) — no skeleton flash. The cached
    // path is force-dynamic on the server, so this client cache is what makes re-opening a sheet feel instant.
    const cached = enginePeek<StrategyDetailResponse>(`/strategies/${id}`);
    if (cached) {
      setDetail(cached);
      setState("idle");
      return;
    }
    let cancelled = false;
    setState("loading");
    setDetail(null);
    engineGetJson<StrategyDetailResponse>(`/strategies/${id}`)
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <SidePanel open={!!id} onClose={onClose} title={detail?.name ?? (id ? "Loading…" : "—")}>
      {state === "loading" ? (
        <div className="skel" style={{ height: 320 }} />
      ) : state === "error" ? (
        <p className="quiet" style={{ fontSize: 12, padding: "20px 4px" }}>Could not load this Version&apos;s detail — the engine did not respond.</p>
      ) : detail ? (
        <StrategySheet strategy={detail} stageOverride={stage} />
      ) : null}
    </SidePanel>
  );
}
