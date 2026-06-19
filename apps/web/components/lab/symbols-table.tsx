"use client";

// module: the Strategies SCREENER — one row per (algorithm × asset × venue) TRIPLET, never pooled. Each row is a
// strategy on one symbol at one venue, ranked by standalone net-of-fee return. Restores the OG strategies-page UX
// on the granular rows: row click → right SIDE PANEL with the full strategy sheet; a COLUMN PICKER; the DARK-MODE
// toggle; plus multi-select STRATEGY / SYMBOL / VENUE / STATUS filters (search + checkbox + selected-first). Rows
// are PAGINATED (100 max per page). Each row's IDENTITY is its stable COMBO "#n" — assigned per distinct
// (algo × symbol × venue) cell via a deterministic key sort, so a combo keeps its number across any sort / filter
// / page; a fainter algorithm "#n" rides behind it for recognising the same algo across its cells. Clicking a row
// selects only THAT cell (per-triplet highlight) while the side panel opens the whole VERSION. Visibility only —
// the deterministic Gate alone funds.
//
// HONESTY: return_pct / max_drawdown are stored as FRACTIONS (0.21 = 21%) → ×100 for display. The per-row badge is
// the LIFECYCLE stage (Backtest / Paper / Live / Killed), BADGE-ONLY — the money path reads forward evidence, not
// this column. The legacy per-symbol "verdict" is no longer surfaced here (filtering is via the dropdowns).

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { LabSymbolRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { SidePanel } from "@/components/ui/side-panel";
import { StrategySheet } from "@/components/strategy/strategy-sheet";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LIFE_BADGE_CLASS, LIFE_LABEL, type LifeStatus } from "@/lib/lifecycle";
import { engineGetJson, enginePeek } from "@/lib/engine";
import { cn, formatPct, formatVenue, isKilled, isPaper } from "@/lib/utils";

// Rows shown per page — never render more than this many <tr> at once (keeps the DOM lean on a fat universe).
const PAGE_SIZE = 100;

// The fiche-triplet URL for a cell (deep-link target; kept for the comparison grid's navigate mode). venue_id is
// carried as "" for a NULL-venue cell so the sibling stays addressable.
export function tripletHref(r: { strategy_version_id: string; symbol: string; venue_id: string | null }): string {
  const qs = new URLSearchParams({ symbol: r.symbol, venue: r.venue_id ?? "" });
  return `/strategy/${r.strategy_version_id}?${qs.toString()}`;
}

export type TripletKey = { strategy_version_id: string; symbol: string; venue_id: string | null };

// The canonical (algo × symbol × venue) identity of a cell — the unit the operator tracks. Keyed on the ALGO
// (strategy_id), NOT the version: a strategy's many near-identical versions on the SAME (symbol, venue) are ONE
// combo, so one triplet = one combo number (the engine already dedups cells to the latest version per triplet).
// venue_id is normalised to "" so a NULL-venue cell has ONE stable key everywhere (the combo-number map). Single
// source of triplet identity.
function comboKeyOf(r: { strategy_id: string; symbol: string; venue_id: string | null }): string {
  return `${r.strategy_id} ${r.symbol} ${r.venue_id ?? ""}`;
}

// Triplet equality — the FULL (version × symbol × venue) compare with the same `?? ""` NULL-venue normalisation
// on both sides. Used for BOTH the comparison-grid highlight and the screener's per-cell self-selection so the
// two never drift (the prior bug: selection compared version-id only, lighting every sibling cell of the algo).
function sameTriplet(a: TripletKey | null | undefined, b: { strategy_version_id: string; symbol: string; venue_id: string | null }): boolean {
  return (
    a != null &&
    a.strategy_version_id === b.strategy_version_id &&
    a.symbol === b.symbol &&
    (a.venue_id ?? "") === (b.venue_id ?? "")
  );
}

type VerdictKey = "robust" | "fragile" | "thin" | "negative";
const VERDICT_META: Record<VerdictKey, { label: string; color: string; dim: string }> = {
  robust: { label: "Robust", color: "var(--up)", dim: "var(--up-dim)" },
  fragile: { label: "Fragile", color: "var(--gold)", dim: "var(--gold-dim)" },
  negative: { label: "Negative", color: "var(--down)", dim: "var(--down-dim)" },
  thin: { label: "Thin", color: "var(--ink-2, #8a8a8a)", dim: "transparent" },
};

// Normalize a raw `strategy_versions.status` string onto the 5-lane LifeStatus taxonomy (lib/lifecycle). Mirrors
// the engine's lifecycle vocabulary: `lab` → queued, `screened` → Backtest, `paper`/`forward_test` → Paper,
// `live` → Live, `killed` → Killed. Reuses the shared isPaper/isKilled predicates so the taxonomy never drifts.
// Anything unknown falls back to the earliest "queued" lane (never fabricates a more-advanced stage).
function lifeStatusOf(status: string | null | undefined): LifeStatus {
  if (isKilled(status)) return "killed";
  if (isPaper(status)) return "paper";
  const s = (status ?? "").toLowerCase();
  if (s === "live") return "live";
  if (s === "screened" || s === "backtested" || s === "backtest") return "screened";
  return "lab";
}

// Is this cell statistically too THIN to judge — fewer trades than the gate's real min_trades floor? Prefer the
// engine-stamped `thin` flag (computed against the live constant); fall back to the row's own trades vs the
// `minTrades` the response carried. An uncomputed (cell-less) row is never "thin" — it has no trades to judge.
function isThin(r: LabSymbolRow, minTrades: number): boolean {
  if (r.symbol === "") return false;
  if (typeof r.thin === "boolean") return r.thin;
  return minTrades > 0 && r.trades < minTrades;
}

// A row with NO computed cell — the engine's synthetic "New" row for an authored-but-uncomputed version. It has
// no symbol (no backtest_symbols cell exists), so an empty symbol IS the signal. Such a version is "New" on THIS
// screener (nothing computed per-symbol) regardless of the parent version's raw pipeline status — so it lands in
// the New lane and is reachable via the Status="New" filter, instead of hiding under Killed/Screened/Paper.
function isUncomputed(r: LabSymbolRow): boolean {
  return r.symbol === "";
}

// The row's lifecycle lane: a cell-less (uncomputed) row is ALWAYS "New" (lab); otherwise the parent version's
// normalized status. Single source for the badge, the Status dropdown, the filter and the status sort.
function rowLifeStatus(r: LabSymbolRow): LifeStatus {
  return isUncomputed(r) ? "lab" : lifeStatusOf(r.status);
}

// The small per-row lifecycle badge (replaces the old Verdict cell). New / Backtest / Paper / Live / Killed,
// reusing the shared stage-badge classes so it matches every other surface.
function LifeBadge({ row }: { row: LabSymbolRow }) {
  const life = rowLifeStatus(row);
  return <span className={LIFE_BADGE_CLASS[life]}>{LIFE_LABEL[life]}</span>;
}

// Sortable column keys. "combo" and "strategy" are the two identity columns (always shown); the rest are pickable.
// The legacy "verdict" column is gone; "status" is the per-row lifecycle stage.
type ColKey = "status" | "return" | "venue" | "symbol" | "trades" | "dd" | "sharpe";
type SortKey = "combo" | "strategy" | ColKey;
type SortDir = "asc" | "desc";

const LIFE_RANK: Record<LifeStatus, number> = { lab: 0, screened: 1, paper: 2, live: 3, killed: -1 };
const SORT_VALUE: Record<SortKey, (r: LabSymbolRow, comboNum?: Map<string, number>) => number | string> = {
  combo: (r, comboNum) => comboNum?.get(comboKeyOf(r)) ?? 0,
  strategy: (r) => r.strategy_name.toLowerCase(),
  symbol: (r) => r.symbol.toLowerCase(),
  venue: (r) => (r.venue_id ?? "").toLowerCase(),
  // The ONE return axis is ANNUALIZED (CAGR) — comparing total returns over different windows is meaningless, so
  // there is no total-return column to sort on. Cells with no recorded window sort last (-Infinity).
  return: (r) => (typeof r.return_pct_annualized === "number" ? r.return_pct_annualized : -Infinity),
  sharpe: (r) => r.sharpe,
  dd: (r) => r.max_drawdown,
  trades: (r) => r.trades,
  status: (r) => LIFE_RANK[rowLifeStatus(r)] ?? 0,
};

// Column order: status · return · venue · symbol · trades · dd · sharpe.
// Sharpe is HIDDEN by default; everything else is visible.
const COLS: { key: ColKey; label: string; align?: "right"; tip?: string }[] = [
  { key: "status", label: "Status", tip: "The lifecycle stage of this Version — Backtest · Paper · Live · Killed. Badge-only; the money path reads forward evidence, not this." },
  { key: "return", label: "Return /yr", align: "right", tip: "ANNUALIZED (CAGR) net-of-fee return on THIS symbol at THIS venue — the ONLY return shown, because comparing totals over different windows is meaningless. Standalone, never a pooled mean. The muted '≥ x%/yr' below is a CONFIDENCE FLOOR (Sharpe standard-error shrinkage) — the estimate net of noise, so a short/thin window isn't read as fact. Short windows amplify — read with Trades/Sharpe and the strat sheet's OOS duration. — = window not yet recorded (re-screened cells fill in)." },
  { key: "venue", label: "Venue" },
  { key: "symbol", label: "Symbol" },
  { key: "trades", label: "Trades", align: "right" },
  { key: "dd", label: "Max DD", align: "right" },
  { key: "sharpe", label: "Sharpe", align: "right" },
];
const DEFAULT_VISIBLE: Record<ColKey, boolean> = { status: true, return: true, venue: true, symbol: true, trades: true, dd: true, sharpe: false };
const DEFAULT_COL_COUNT = Object.values(DEFAULT_VISIBLE).filter(Boolean).length;

// Per-column CSS width class (table-layout:fixed honours these). The identity columns (.col-combo, .col-strat)
// are fixed-size / flex-grow respectively; toggling extra columns adds the min-width floor.
const COL_CLASS: Record<ColKey, string> = {
  status: "col-status",
  return: "col-num",
  venue: "col-venue",
  symbol: "col-sym",
  trades: "col-num-sm",
  dd: "col-num",
  sharpe: "col-num",
};

// VerdictBadge is retained ONLY because the fiche triplet-card still renders a per-cell verdict; the screener
// table no longer uses it (filtering is via the dropdowns, the row badge is the lifecycle stage).
export function VerdictBadge({ verdict }: { verdict: string | null }) {
  const meta = VERDICT_META[(verdict ?? "thin") as VerdictKey] ?? VERDICT_META.thin;
  if (verdict === "thin" || !verdict) return <span className="quiet">{meta.label}</span>;
  return (
    <span
      className="badge"
      style={{ background: meta.dim, color: meta.color, borderColor: meta.color }}
      title={
        verdict === "fragile"
          ? "Net-positive here but the edge does NOT generalize across the tested symbols — a lone/minority winner (best-of-N caution)."
          : verdict === "robust"
            ? "Net-positive here AND the edge generalizes across the tested symbols — corroborated."
            : "Cleared the trade floor but net non-positive on this symbol."
      }
    >
      {meta.label}
    </span>
  );
}

export function SymbolsTable({
  rows,
  symbols,
  venues,
  minTrades = 0,
  title = "Strategies",
  caption = true,
  ribbon,
  highlight,
  navigateOnClick,
}: {
  rows: LabSymbolRow[];
  symbols: string[];
  venues: string[];
  minTrades?: number; // the engine's REAL gate trade floor — a cell below it is "thin" (too few trades to judge)
  title?: string;
  caption?: boolean;
  ribbon?: React.ReactNode;
  highlight?: TripletKey;
  navigateOnClick?: boolean; // comparison grid: a row navigates to the sibling triplet fiche; omitted → side panel
}) {
  const router = useRouter();
  // Deep-link: ?v=<version_id> opens that strategy's sheet on load; optional ?symbol=&venue= PIN the exact
  // (algo × symbol × venue) combo so the matching row is selected + highlighted + scrolled into view (and its
  // page jumped to). A link from /paper / any dashboard lands on the precise cell, not just the algorithm.
  const searchParams = useSearchParams();
  const deepLink = useMemo(() => {
    const v = searchParams.get("v");
    if (!v) return null;
    return { version_id: v, symbol: searchParams.get("symbol"), venue: searchParams.get("venue") };
    // Read once at mount (the URL is the initial intent). No re-sync effect — consistent with the prior code.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [strategySel, setStrategySel] = useState<Set<string>>(new Set());
  const [symbolSel, setSymbolSel] = useState<Set<string>>(new Set());
  const [venueSel, setVenueSel] = useState<Set<string>>(new Set());
  const [statusSel, setStatusSel] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "return", dir: "desc" });
  const [visible, setVisible] = useState<Record<ColKey, boolean>>({ ...DEFAULT_VISIBLE });
  const [showPicker, setShowPicker] = useState(false);
  // Two DISTINCT pieces of selection: the per-VERSION sheet id (the side panel shows the whole Version) and the
  // per-CELL triplet highlight (only the clicked row lights up). The deep-link opens the sheet by version; the
  // triplet is pinned only when ?symbol= (and optionally ?venue=) is present.
  const [sheetVersionId, setSheetVersionId] = useState<string | null>(deepLink?.version_id ?? null);
  // The clicked ROW itself (a backtest_symbols cell) — passed to the sheet so its backtest-phase headline reads
  // this cell's STANDALONE truth (Return / Max DD / Trades + equity) instead of the version's pooled aggregate
  // (which for a brut-converted combo carries garbage, e.g. 505% DD). null on a deep-link with no row resolved.
  const [sheetCell, setSheetCell] = useState<LabSymbolRow | null>(null);
  const [selectedTriplet, setSelectedTriplet] = useState<TripletKey | null>(
    deepLink && deepLink.symbol != null
      ? { strategy_version_id: deepLink.version_id, symbol: deepLink.symbol, venue_id: deepLink.venue ?? "" }
      : null,
  );
  const [page, setPage] = useState(0);
  const pickerRef = useRef<HTMLDivElement>(null);
  const selectedRowRef = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    if (!showPicker) return;
    const onDoc = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setShowPicker(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showPicker]);

  // ── COMBO NUMBER (the PRIMARY identity the operator tracks): a stable #N for each DISTINCT (algo × symbol ×
  // venue) triplet, assigned via a DETERMINISTIC sort of the triplet key — by strategy_name, then symbol, then
  // venue — computed once over ALL rows. A combo therefore keeps its number regardless of the current sort,
  // filter or page. This is the prominent leftmost pill. ──
  const comboNumber = useMemo(() => {
    const seen = new Map<string, { strategy_name: string; symbol: string; venue: string }>();
    for (const r of rows) {
      const k = comboKeyOf(r);
      if (!seen.has(k)) seen.set(k, { strategy_name: r.strategy_name, symbol: r.symbol, venue: r.venue_id ?? "" });
    }
    const ordered = Array.from(seen.entries()).sort(([, a], [, b]) => {
      const byName = a.strategy_name.localeCompare(b.strategy_name);
      if (byName !== 0) return byName;
      const bySym = a.symbol.localeCompare(b.symbol);
      if (bySym !== 0) return bySym;
      return a.venue.localeCompare(b.venue);
    });
    const map = new Map<string, number>();
    ordered.forEach(([k], i) => map.set(k, i + 1));
    return map;
  }, [rows]);

  // ── Stable algorithm number (SECONDARY, subtle): #1, #2, … per DISTINCT strategy_name, computed once over ALL
  // rows so the number is identical regardless of paging, sort or the active filters. Numbered by AUTHORING ORDER
  // (each strategy's EARLIEST cell created_at): #1 = first authored, #N = latest. So a HIGHER number = a NEWER
  // strategy, which is what the Strategies dropdown's number-descending order (latest first) relies on. Ties on
  // created_at fall back to name for determinism. Rendered muted — the combo number above is the identity. ──
  const strategyNumber = useMemo(() => {
    const firstSeen = new Map<string, number>();
    for (const r of rows) {
      const t = Date.parse(r.created_at);
      const ts = Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
      const prev = firstSeen.get(r.strategy_name);
      if (prev === undefined || ts < prev) firstSeen.set(r.strategy_name, ts);
    }
    const names = Array.from(firstSeen.keys()).sort((a, b) => {
      const ta = firstSeen.get(a)!;
      const tb = firstSeen.get(b)!;
      if (ta !== tb) return ta - tb;
      return a.localeCompare(b);
    });
    const map = new Map<string, number>();
    names.forEach((n, i) => map.set(n, i + 1));
    return map;
  }, [rows]);

  // Distinct strategy names (for the Strategy dropdown), sorted the same way as the number map so labels read #1…#n.
  const strategyOptions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.strategy_name))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );

  // The lifecycle lanes actually PRESENT in the rows (for the Status dropdown), ordered by pipeline stage. Uses
  // the row-level lane so a cell-less uncomputed row registers the "New" (lab) lane — making it selectable even
  // though no parent version carries a literal lab status.
  const statusOptions = useMemo(() => {
    const present = new Set<LifeStatus>();
    for (const r of rows) present.add(rowLifeStatus(r));
    const order: LifeStatus[] = ["lab", "screened", "paper", "live", "killed"];
    return order.filter((s) => present.has(s));
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = rows.filter((r) => {
      if (strategySel.size && !strategySel.has(r.strategy_name)) return false;
      if (symbolSel.size && !symbolSel.has(r.symbol)) return false;
      if (venueSel.size && !venueSel.has(r.venue_id ?? "")) return false;
      if (statusSel.size && !statusSel.has(rowLifeStatus(r))) return false;
      if (q && !r.strategy_name.toLowerCase().includes(q) && !r.symbol.toLowerCase().includes(q)) return false;
      return true;
    });
    const val = SORT_VALUE[sort.key];
    out.sort((a, b) => {
      const va = val(a, comboNumber);
      const vb = val(b, comboNumber);
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, strategySel, symbolSel, venueSel, statusSel, query, sort, comboNumber]);

  // ── Pagination: clamp to a max of PAGE_SIZE rows on screen; reset to page 1 whenever the filtered set changes
  // (any filter, search or sort change) so the operator never lands on an out-of-range / stale page. ──
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  useEffect(() => {
    setPage(0);
  }, [strategySel, symbolSel, venueSel, statusSel, query, sort]);

  // The position (in the global filtered+sorted order) of the deep-linked combo, so we can jump to its PAGE and
  // scroll it into view. Pin precision degrades gracefully with what the link carries:
  //   ?v=&symbol=&venue=  → the EXACT (algo × symbol × venue) cell
  //   ?v=&venue=          → the version's first row AT that venue (a /paper link with no traded symbol field)
  //   ?v=                 → the version's first row
  // -1 when nothing is pinned or the combo isn't in the current set.
  const deepLinkIndex = useMemo(() => {
    if (!deepLink) return -1;
    if (deepLink.symbol != null) {
      const want: TripletKey = { strategy_version_id: deepLink.version_id, symbol: deepLink.symbol, venue_id: deepLink.venue ?? "" };
      return filtered.findIndex((r) => sameTriplet(want, r));
    }
    if (deepLink.venue) {
      const idx = filtered.findIndex((r) => r.strategy_version_id === deepLink.version_id && (r.venue_id ?? "") === deepLink.venue);
      if (idx >= 0) return idx;
    }
    return filtered.findIndex((r) => r.strategy_version_id === deepLink.version_id);
  }, [deepLink, filtered]);

  // Once at mount: if a deep link resolves to a row, jump to its page and pin the per-cell highlight (so ONLY
  // that row lights up, even on a ?v=-only link → its first row). The scroll-into-view happens in a SEPARATE
  // effect below, once the target row is actually committed to the DOM on the (possibly newly-set) page.
  const deepLinkDone = useRef(false);
  const deepLinkScrolled = useRef(false);
  useEffect(() => {
    if (deepLinkDone.current || deepLinkIndex < 0) return;
    deepLinkDone.current = true;
    setPage(Math.floor(deepLinkIndex / PAGE_SIZE));
    const r = filtered[deepLinkIndex];
    if (r) {
      setSelectedTriplet({ strategy_version_id: r.strategy_version_id, symbol: r.symbol, venue_id: r.venue_id });
      // A deep-linked sheet (opened via ?v= on load) also reads the resolved cell's standalone truth (unless the
      // resolved row is uncomputed — then no per-cell numbers exist, keep the sheet on its honest fallbacks).
      if (sheetVersionId === r.strategy_version_id) setSheetCell(isUncomputed(r) ? null : r);
    }
  }, [deepLinkIndex, filtered, sheetVersionId]);

  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageRows = filtered.slice(pageStart, pageStart + PAGE_SIZE);
  const rangeFrom = filtered.length === 0 ? 0 : pageStart + 1;
  const rangeTo = Math.min(pageStart + PAGE_SIZE, filtered.length);

  // Scroll the deep-linked row into view ONCE, after the page-jump + highlight have rendered it into the DOM
  // (the ref is attached only to the selected <tr>). Depends on pageRows so it re-checks once the target page
  // commits. Guarded so a later manual click never re-triggers a scroll.
  useEffect(() => {
    if (deepLinkScrolled.current || deepLinkIndex < 0 || !selectedRowRef.current) return;
    deepLinkScrolled.current = true;
    selectedRowRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [deepLinkIndex, selectedTriplet, pageRows]);

  const visibleCols = COLS.filter((c) => visible[c.key]);
  // DEFAULT columns are sized to FIT the container with no horizontal scroll on load (explicit per-column
  // widths via table-layout:fixed, see globals.css). Only force a min-width — triggering the scroll — when the
  // operator toggles ON more than the default set, so the extra columns get room rather than crushing.
  const minWidth = visibleCols.length > DEFAULT_COL_COUNT ? 200 + visibleCols.length * 96 : undefined;

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "strategy" || key === "symbol" || key === "venue" ? "asc" : "desc" }));
  }

  function handleRow(r: LabSymbolRow) {
    if (navigateOnClick) {
      router.push(tripletHref(r));
      return;
    }
    // Per-cell selection (the highlight) + per-version sheet (the side panel shows the whole Version). The two
    // are DISTINCT: clicking one cell highlights only THAT row, never every sibling cell of the same algo.
    setSelectedTriplet({ strategy_version_id: r.strategy_version_id, symbol: r.symbol, venue_id: r.venue_id });
    setSheetVersionId(r.strategy_version_id);
    // An uncomputed (cell-less) row carries zeroed synthetic metrics — never feed those to the sheet as a "cell"
    // (it would read +0.0% / 0 trades as if real). The sheet then falls back to its honest pooled/empty states.
    setSheetCell(isUncomputed(r) ? null : r);
  }

  function renderCell(r: LabSymbolRow, key: ColKey) {
    // An uncomputed (cell-less "New") row has no symbol/venue and its metrics are zeroed placeholders, NOT real
    // results — render an explicit "—" so a not-yet-backtested version never reads as a flat 0% / 0-trade result.
    const uncomputed = isUncomputed(r);
    const thin = isThin(r, minTrades);
    switch (key) {
      case "symbol":
        return <td key={key} className={uncomputed ? "quiet" : undefined}>{uncomputed ? "—" : r.symbol}</td>;
      case "venue":
        return <td key={key} className={r.venue_id ? undefined : "quiet"}>{uncomputed ? "—" : formatVenue(r.venue_id)}</td>;
      case "return": {
        // The ONE return column = ANNUALIZED (CAGR). "—" when no OOS window is recorded for the cell (can't annualize).
        if (uncomputed || typeof r.return_pct_annualized !== "number") {
          return <td key={key} style={{ textAlign: "right" }} className="quiet">—</td>;
        }
        const ann = r.return_pct_annualized;
        // Confidence lower-bound (Fix 1): the engine's Sharpe-SE shrinkage floor — shown as a muted "≥ x%/yr"
        // secondary line so the point CAGR is never read as fact. Omitted when too thin to estimate (null). A THIN
        // cell (below the gate floor) mutes the whole figure so a 3-trade cell never visually outranks a 300-trade one.
        const lo = typeof r.return_pct_annualized_lo === "number" ? r.return_pct_annualized_lo : null;
        return (
          <td key={key} style={{ textAlign: "right", opacity: thin ? 0.5 : undefined }}
              title={thin ? `Thin sample — only ${r.trades} trades (below the ${minTrades}-trade floor): too few to judge this CAGR honestly.` : undefined}>
            <span style={{ color: ann >= 0 ? "var(--up)" : "var(--down)" }}>{formatPct(ann * 100)}<span className="quiet" style={{ fontSize: "0.85em" }}>/yr</span></span>
            {lo !== null ? (
              <span className="quiet" style={{ display: "block", fontSize: "0.8em", lineHeight: 1.1 }}
                    title="Conservative confidence floor (Sharpe standard-error shrinkage) — the return is at LEAST this, net of estimation noise.">
                ≥ {formatPct(lo * 100)}/yr
              </span>
            ) : null}
          </td>
        );
      }
      case "sharpe":
        return <td key={key} style={{ textAlign: "right" }} className={uncomputed ? "quiet" : undefined}>{uncomputed ? "—" : Number.isFinite(r.sharpe) ? r.sharpe.toFixed(2) : "—"}</td>;
      case "dd":
        return <td key={key} style={{ textAlign: "right" }} className="quiet">{uncomputed ? "—" : `${(r.max_drawdown * 100).toFixed(1)}%`}</td>;
      case "trades":
        // Thin-sample flag (Fix 2): a cell below the gate's real min_trades floor carries a small muted "thin" chip
        // next to its count, so a 3-trade cell is visually distinct from a 300-trade one.
        return (
          <td key={key} style={{ textAlign: "right" }} className={uncomputed ? "quiet" : undefined}>
            {uncomputed ? "—" : (
              <>
                {thin ? <span className="badge" style={{ marginRight: 4, fontSize: "0.7em", background: "transparent", color: "var(--ink-2, #8a8a8a)", borderColor: "var(--ink-2, #8a8a8a)" }} title={`Thin sample — below the ${minTrades}-trade floor the gate needs to judge a cell honestly.`}>thin</span> : null}
                {r.trades}
              </>
            )}
          </td>
        );
      case "status":
        return <td key={key}><LifeBadge row={r} /></td>;
    }
  }

  return (
    <>
      {/* ── ONE-ROW toolbar: title + every filter dropdown (Strategies · Symbols · Venues · Status) + search +
          Columns picker + dark-mode toggle, all on a single flex row (wraps only as a last resort). ── */}
      <div className="toolbar-row screener-toolbar" style={{ marginBottom: 8 }}>
        <span className="page-title">{title}</span>
        <MultiSelect
          label="strategies"
          options={strategyOptions}
          selected={strategySel}
          onChange={setStrategySel}
          renderOption={(o) => `#${strategyNumber.get(o) ?? "?"} ${o}`}
          // Unselected strategies ordered by NUMBER DESCENDING (highest = latest authored first) so new
          // strategies surface at the top, not buried under the alphabetical run.
          orderUnselected={(a, b) => (strategyNumber.get(b) ?? 0) - (strategyNumber.get(a) ?? 0)}
        />
        <MultiSelect label="symbols" options={symbols} selected={symbolSel} onChange={setSymbolSel} />
        <MultiSelect label="venues" options={venues} selected={venueSel} onChange={setVenueSel} renderOption={(v) => formatVenue(v)} formatValue={(v) => formatVenue(v)} />
        <MultiSelect
          label="status"
          options={statusOptions}
          selected={statusSel}
          onChange={(next) => setStatusSel(next)}
          renderOption={(o) => LIFE_LABEL[o as LifeStatus] ?? o}
          formatValue={(o) => LIFE_LABEL[o as LifeStatus] ?? o}
        />
        <input className="search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search strategy or symbol…" aria-label="Search" style={{ minWidth: 150 }} />
        <div className="col-picker-wrap" ref={pickerRef} style={{ marginLeft: "auto" }}>
          <button type="button" className="btn-col-picker" onClick={() => setShowPicker((v) => !v)} aria-expanded={showPicker}>Columns</button>
          <div className={cn("col-picker-menu cp-1", showPicker && "open")}>
            <div className="cp-head">Show columns</div>
            {COLS.map((c) => (
              <div key={c.key} className={cn("col-picker-item", visible[c.key] && "on")} onClick={() => setVisible((v) => ({ ...v, [c.key]: !v[c.key] }))}>
                <span className="cp-ind" />
                <span className="cp-label">{c.label}</span>
              </div>
            ))}
            <div className="col-picker-divider" />
            <button type="button" className="cp-reset" onClick={() => setVisible({ ...DEFAULT_VISIBLE })}>Reset to default</button>
          </div>
        </div>
        <ThemeToggle />
      </div>

      {ribbon ? <div style={{ marginBottom: 8 }}>{ribbon}</div> : null}

      {caption ? (
        <p className="quiet" style={{ fontSize: 11, margin: "0 4px 8px" }}>
          Each row is one strategy on one symbol at one venue — the granular triplet, never a pooled mean. Ranked by
          standalone return. The badge shows the lifecycle stage (Backtest · Paper · Live · Killed). Filter with the
          Strategies / Symbols / Venues / Status dropdowns; click a row to open its sheet. The deterministic Gate
          alone decides funding.
        </p>
      ) : null}

      <div className={cn("screener-wrap", sheetVersionId && "panel-open")}>
        {filtered.length === 0 ? (
          <p className="quiet" style={{ fontSize: 12, padding: "24px 4px", textAlign: "center" }}>No strategies match these filters.</p>
        ) : (
          <table className="screener-table" style={minWidth !== undefined ? { minWidth } : undefined}>
            <colgroup>
              <col className="col-combo" />
              <col className="col-strat" />
              {visibleCols.map((c) => (
                <col key={c.key} className={COL_CLASS[c.key]} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th onClick={() => toggleSort("combo")} style={{ cursor: "pointer" }}>
                  <div className="th-inner">Combo<span className={cn("sort-ind", sort.key === "combo" && (sort.dir === "asc" ? "asc" : "desc"))} /></div>
                </th>
                <th onClick={() => toggleSort("strategy")} style={{ cursor: "pointer" }}>
                  <div className="th-inner">Strategy<span className={cn("sort-ind", sort.key === "strategy" && (sort.dir === "asc" ? "asc" : "desc"))} /></div>
                </th>
                {visibleCols.map((c) => (
                  <th key={c.key} onClick={() => toggleSort(c.key)} title={c.tip} style={{ cursor: "pointer", textAlign: c.align ?? "left" }}>
                    <div className="th-inner" style={c.align === "right" ? { justifyContent: "flex-end" } : undefined}>
                      {c.label}
                      <span className={cn("sort-ind", sort.key === c.key && (sort.dir === "asc" ? "asc" : "desc"))} />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r, i) => {
                // Comparison-grid highlight (the clicked sibling, from the `highlight` prop) AND the screener's
                // own per-cell selection both use the SAME full-triplet compare — only THIS row, never every
                // sibling cell of the algo.
                const isCurrent = sameTriplet(highlight ?? null, r);
                const isSelected = sameTriplet(selectedTriplet, r);
                const comboNum = comboNumber.get(comboKeyOf(r));
                const stratNum = strategyNumber.get(r.strategy_name);
                return (
                  <tr
                    key={`${r.strategy_version_id}-${r.symbol}-${r.venue_id ?? ""}-${pageStart + i}`}
                    ref={isSelected ? selectedRowRef : undefined}
                    onClick={() => handleRow(r)}
                    className={cn(isCurrent && "row-current", isSelected && "sel")}
                    style={{ cursor: "pointer", ...(isCurrent ? { background: "var(--iris-dim, rgba(120,120,255,0.08))" } : {}) }}
                    title="Open this strategy"
                  >
                    <td>
                      {comboNum !== undefined ? <span className="combo-num" title={`Combo #${comboNum} — this strategy on this symbol at this venue`}>#{comboNum}</span> : null}
                    </td>
                    {/* STRATEGY: width-capped + ellipsis. The combo/algo "#n" prefix and the LLM badge stay
                        flex-shrink:0 (always visible); only the long name ellipsizes inside .strat-name. The
                        full name shows on the shared #tipbox tooltip (data-tip) after a deliberate hover rest. */}
                    <td className="strat-cell" data-tip={r.strategy_name}>
                      {stratNum !== undefined ? <span className="strat-num-sub" title={`Algorithm #${stratNum}`}>#{stratNum}</span> : null}
                      <span className="strat-name">{r.strategy_name}</span>
                      {r.kind === "llm" ? <span className="badge badge-iris strat-llm">LLM</span> : null}
                    </td>
                    {visibleCols.map((c) => renderCell(r, c.key))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Pager: page X / Y + the visible range + prev/next arrows. Only shown when there's more than one page. ── */}
      {filtered.length > 0 ? (
        <div className="screener-pager">
          <span className="quiet">
            {/* Fixed 'en-US' grouping — bare toLocaleString() differs server vs client → hydration mismatch. */}
            {rangeFrom.toLocaleString("en-US")}–{rangeTo.toLocaleString("en-US")} of {filtered.length.toLocaleString("en-US")}
          </span>
          {pageCount > 1 ? (
            <div className="pager-ctrl">
              <button
                type="button"
                className="pager-btn"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={safePage <= 0}
                aria-label="Previous page"
              >
                ‹
              </button>
              <span className="pager-pos">Page {safePage + 1} / {pageCount}</span>
              <button
                type="button"
                className="pager-btn"
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                disabled={safePage >= pageCount - 1}
                aria-label="Next page"
              >
                ›
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* The side panel stays keyed by VERSION (it shows the whole Version) but carries the clicked CELL so the
          backtest-phase headline reads that cell's standalone truth. Closing it drops the sheet, the cell, and
          the per-cell row highlight so the table returns to a clean unselected state. */}
      <SheetPanel id={sheetVersionId} cell={sheetCell} onClose={() => { setSheetVersionId(null); setSheetCell(null); setSelectedTriplet(null); }} />
    </>
  );
}

// ── the right detail sheet — fetches the full Version detail client-side (via the same-origin proxy) and renders
// the SHARED StrategySheet. Honest loading + error states. Ported from the OG strategies page (the regression fix). ──
function SheetPanel({ id, cell, onClose }: { id: string | null; cell?: LabSymbolRow | null; onClose: () => void }) {
  const [detail, setDetail] = useState<StrategyDetailResponse | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");

  useEffect(() => {
    if (!id) {
      setDetail(null);
      setState("idle");
      return;
    }
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
        <p className="quiet" style={{ fontSize: 12, padding: "20px 4px" }}>Could not load this strategy&apos;s detail — the engine did not respond.</p>
      ) : detail ? (
        <StrategySheet strategy={detail} cell={cell} />
      ) : null}
    </SidePanel>
  );
}

// A multi-select dropdown — click the button, search the options, click rows to toggle several. Selected options
// FLOAT TO THE TOP (selected-first, then the rest) so the picks are visible at a glance; each option carries a
// real checkbox. `renderOption`/`formatValue` let a caller show a friendlier label than the raw option value
// (e.g. "#3 momentum" for a strategy, "Paper" for a status lane). `orderUnselected` overrides how the UNSELECTED
// items are ordered (selected-first is always honoured first) — the Strategies dropdown passes a number-DESC
// comparator (latest #N first); Symbols/Venues keep the default A→Z label sort.
function MultiSelect({
  label,
  options,
  selected,
  onChange,
  renderOption,
  formatValue,
  orderUnselected,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  renderOption?: (o: string) => string;
  formatValue?: (o: string) => string;
  orderUnselected?: (a: string, b: string) => number;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const optLabel = (o: string) => (renderOption ? renderOption(o) : o || "—");
  const valLabel = (o: string) => (formatValue ? formatValue(o) : o || "—");

  // Filter by the rendered label OR the raw value, then SELECTED-FIRST so picks float to the top. Within each
  // group the order is `orderUnselected` if provided (Strategies → number-desc), else A→Z by rendered label.
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const matched = options.filter(
      (o) => optLabel(o).toLowerCase().includes(needle) || o.toLowerCase().includes(needle),
    );
    const within = orderUnselected ?? ((a: string, b: string) => optLabel(a).localeCompare(optLabel(b)));
    return matched.slice().sort((a, b) => {
      const sa = selected.has(a) ? 0 : 1;
      const sb = selected.has(b) ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return within(a, b);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, q, selected, renderOption, orderUnselected]);

  // Button label: "All X" when empty (clickable opener); the single value when one is picked; else "n X".
  const btnLabel =
    selected.size === 0
      ? `All ${label}`
      : selected.size === 1
        ? valLabel(Array.from(selected)[0])
        : `${selected.size} ${label}`;

  function toggle(o: string) {
    const n = new Set(selected);
    if (n.has(o)) n.delete(o);
    else n.add(o);
    onChange(n);
  }

  return (
    <div className="col-picker-wrap ms-wrap" ref={ref}>
      <button type="button" className={cn("btn-col-picker", selected.size > 0 && "active")} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {btnLabel}
        <span className="ms-caret">▾</span>
      </button>
      <div className={cn("col-picker-menu cp-1", open && "open")} style={{ minWidth: 200, left: 0, right: "auto", transformOrigin: "top left" }}>
        <input className="search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${label}…`} style={{ width: "100%", marginBottom: 6 }} />
        {selected.size > 0 ? (
          <button type="button" className="cp-reset" style={{ marginBottom: 2 }} onClick={() => onChange(new Set())}>
            Clear ({selected.size})
          </button>
        ) : null}
        <div style={{ maxHeight: 260, overflowY: "auto" }}>
          {shown.map((o) => (
            <div key={o} className={cn("col-picker-item", selected.has(o) && "on")} onClick={() => toggle(o)}>
              <span className="cp-ind" />
              <span className="cp-label">{optLabel(o)}</span>
            </div>
          ))}
          {shown.length === 0 ? <p className="quiet" style={{ fontSize: 11, padding: 6 }}>No match.</p> : null}
        </div>
      </div>
    </div>
  );
}
