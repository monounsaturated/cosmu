"use client";

// module: the Strategies SCREENER — one row per (algorithm × asset × venue) TRIPLET, never pooled. Each row is a
// strategy on one symbol at one venue, ranked by standalone net-of-fee return. Restores the OG strategies-page UX
// on the granular rows: row click → right SIDE PANEL with the full strategy sheet; a COLUMN PICKER; the DARK-MODE
// toggle; plus multi-select STRATEGY / SYMBOL / VENUE / STATUS filters (search + checkbox + selected-first). Rows
// are PAGINATED (100 max per page) and each algorithm carries a small stable "#n" number so the same algo is
// recognisable across its asset/venue cells. Visibility only — the deterministic Gate alone funds.
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
import { cn, formatPct, isKilled, isPaper } from "@/lib/utils";

// Rows shown per page — never render more than this many <tr> at once (keeps the DOM lean on a fat universe).
const PAGE_SIZE = 100;

// The fiche-triplet URL for a cell (deep-link target; kept for the comparison grid's navigate mode). venue_id is
// carried as "" for a NULL-venue cell so the sibling stays addressable.
export function tripletHref(r: { strategy_version_id: string; symbol: string; venue_id: string | null }): string {
  const qs = new URLSearchParams({ symbol: r.symbol, venue: r.venue_id ?? "" });
  return `/strategy/${r.strategy_version_id}?${qs.toString()}`;
}

export type TripletKey = { strategy_version_id: string; symbol: string; venue_id: string | null };

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

// The small per-row lifecycle badge (replaces the old Verdict cell). Backtest / Paper / Live / Killed, reusing the
// shared stage-badge classes so it matches every other surface.
function LifeBadge({ status }: { status: string | null | undefined }) {
  const life = lifeStatusOf(status);
  return <span className={LIFE_BADGE_CLASS[life]}>{LIFE_LABEL[life]}</span>;
}

// Sortable column keys. "strategy" is the identity column (always shown); the rest are pickable. The legacy
// "verdict" column is gone; "status" is the per-row lifecycle stage.
type ColKey = "symbol" | "venue" | "return" | "sharpe" | "dd" | "trades" | "status";
type SortKey = "strategy" | ColKey;
type SortDir = "asc" | "desc";

const LIFE_RANK: Record<LifeStatus, number> = { lab: 0, screened: 1, paper: 2, live: 3, killed: -1 };
const SORT_VALUE: Record<SortKey, (r: LabSymbolRow) => number | string> = {
  strategy: (r) => r.strategy_name.toLowerCase(),
  symbol: (r) => r.symbol.toLowerCase(),
  venue: (r) => (r.venue_id ?? "").toLowerCase(),
  return: (r) => r.return_pct,
  sharpe: (r) => r.sharpe,
  dd: (r) => r.max_drawdown,
  trades: (r) => r.trades,
  status: (r) => LIFE_RANK[lifeStatusOf(r.status)] ?? 0,
};

const COLS: { key: ColKey; label: string; align?: "right"; tip?: string }[] = [
  { key: "symbol", label: "Symbol" },
  { key: "venue", label: "Venue" },
  { key: "return", label: "Return", align: "right", tip: "Standalone net-of-fee return on THIS symbol at THIS venue — the truth, never a pooled mean." },
  { key: "sharpe", label: "Sharpe", align: "right" },
  { key: "dd", label: "Max DD", align: "right" },
  { key: "trades", label: "Trades", align: "right" },
  { key: "status", label: "Status", tip: "The lifecycle stage of this Version — Backtest · Paper · Live · Killed. Badge-only; the money path reads forward evidence, not this." },
];
const DEFAULT_VISIBLE: Record<ColKey, boolean> = { symbol: true, venue: true, return: true, sharpe: true, dd: true, trades: true, status: true };

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
  title = "Strategies",
  caption = true,
  ribbon,
  highlight,
  navigateOnClick,
}: {
  rows: LabSymbolRow[];
  symbols: string[];
  venues: string[];
  title?: string;
  caption?: boolean;
  ribbon?: React.ReactNode;
  highlight?: TripletKey;
  navigateOnClick?: boolean; // comparison grid: a row navigates to the sibling triplet fiche; omitted → side panel
}) {
  const router = useRouter();
  // Deep-link: ?v=<version_id> opens that strategy's sheet on load (a link from any dashboard lands on it).
  const searchParams = useSearchParams();
  const [strategySel, setStrategySel] = useState<Set<string>>(new Set());
  const [symbolSel, setSymbolSel] = useState<Set<string>>(new Set());
  const [venueSel, setVenueSel] = useState<Set<string>>(new Set());
  const [statusSel, setStatusSel] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "return", dir: "desc" });
  const [visible, setVisible] = useState<Record<ColKey, boolean>>({ ...DEFAULT_VISIBLE });
  const [showPicker, setShowPicker] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("v"));
  const [page, setPage] = useState(0);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPicker) return;
    const onDoc = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setShowPicker(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showPicker]);

  // ── Stable algorithm number: assign #1, #2, … to each DISTINCT strategy_name (sorted), computed once over ALL
  // rows so the number is identical regardless of paging, sort or the active filters. A small additive badge in
  // the Strategy cell so the operator recognises the same algorithm across its asset/venue cells. ──
  const strategyNumber = useMemo(() => {
    const names = Array.from(new Set(rows.map((r) => r.strategy_name))).sort((a, b) => a.localeCompare(b));
    const map = new Map<string, number>();
    names.forEach((n, i) => map.set(n, i + 1));
    return map;
  }, [rows]);

  // Distinct strategy names (for the Strategy dropdown), sorted the same way as the number map so labels read #1…#n.
  const strategyOptions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.strategy_name))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );

  // The lifecycle statuses actually PRESENT in the rows (for the Status dropdown), ordered by pipeline stage.
  const statusOptions = useMemo(() => {
    const present = new Set<LifeStatus>();
    for (const r of rows) present.add(lifeStatusOf(r.status));
    const order: LifeStatus[] = ["lab", "screened", "paper", "live", "killed"];
    return order.filter((s) => present.has(s));
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = rows.filter((r) => {
      if (strategySel.size && !strategySel.has(r.strategy_name)) return false;
      if (symbolSel.size && !symbolSel.has(r.symbol)) return false;
      if (venueSel.size && !venueSel.has(r.venue_id ?? "")) return false;
      if (statusSel.size && !statusSel.has(lifeStatusOf(r.status))) return false;
      if (q && !r.strategy_name.toLowerCase().includes(q) && !r.symbol.toLowerCase().includes(q)) return false;
      return true;
    });
    const val = SORT_VALUE[sort.key];
    out.sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return out;
  }, [rows, strategySel, symbolSel, venueSel, statusSel, query, sort]);

  // ── Pagination: clamp to a max of PAGE_SIZE rows on screen; reset to page 1 whenever the filtered set changes
  // (any filter, search or sort change) so the operator never lands on an out-of-range / stale page. ──
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  useEffect(() => {
    setPage(0);
  }, [strategySel, symbolSel, venueSel, statusSel, query, sort]);
  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageRows = filtered.slice(pageStart, pageStart + PAGE_SIZE);
  const rangeFrom = filtered.length === 0 ? 0 : pageStart + 1;
  const rangeTo = Math.min(pageStart + PAGE_SIZE, filtered.length);

  const visibleCols = COLS.filter((c) => visible[c.key]);
  const minWidth = 200 + visibleCols.length * 96;

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "strategy" || key === "symbol" || key === "venue" ? "asc" : "desc" }));
  }

  function handleRow(r: LabSymbolRow) {
    if (navigateOnClick) router.push(tripletHref(r));
    else setSelectedId(r.strategy_version_id);
  }

  function renderCell(r: LabSymbolRow, key: ColKey) {
    switch (key) {
      case "symbol":
        return <td key={key}>{r.symbol}</td>;
      case "venue":
        return <td key={key} className={r.venue_id ? undefined : "quiet"}>{r.venue_id ?? "—"}</td>;
      case "return":
        return <td key={key} style={{ textAlign: "right", color: r.return_pct >= 0 ? "var(--up)" : "var(--down)" }}>{formatPct(r.return_pct * 100)}</td>;
      case "sharpe":
        return <td key={key} style={{ textAlign: "right" }}>{Number.isFinite(r.sharpe) ? r.sharpe.toFixed(2) : "—"}</td>;
      case "dd":
        return <td key={key} style={{ textAlign: "right" }} className="quiet">{`${(r.max_drawdown * 100).toFixed(1)}%`}</td>;
      case "trades":
        return <td key={key} style={{ textAlign: "right" }}>{r.trades}</td>;
      case "status":
        return <td key={key}><LifeBadge status={r.status} /></td>;
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
        />
        <MultiSelect label="symbols" options={symbols} selected={symbolSel} onChange={setSymbolSel} />
        <MultiSelect label="venues" options={venues} selected={venueSel} onChange={setVenueSel} formatValue={(v) => v || "—"} />
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

      <div className={cn("screener-wrap", selectedId && "panel-open")}>
        {filtered.length === 0 ? (
          <p className="quiet" style={{ fontSize: 12, padding: "24px 4px", textAlign: "center" }}>No strategies match these filters.</p>
        ) : (
          <table className="screener-table" style={{ minWidth }}>
            <colgroup>
              <col style={{ width: 200 }} />
              {visibleCols.map((c) => (
                <col key={c.key} />
              ))}
            </colgroup>
            <thead>
              <tr>
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
                const isCurrent =
                  highlight !== undefined &&
                  highlight.strategy_version_id === r.strategy_version_id &&
                  highlight.symbol === r.symbol &&
                  (highlight.venue_id ?? "") === (r.venue_id ?? "");
                const isSelected = selectedId === r.strategy_version_id;
                const num = strategyNumber.get(r.strategy_name);
                return (
                  <tr
                    key={`${r.strategy_version_id}-${r.symbol}-${r.venue_id ?? ""}-${pageStart + i}`}
                    onClick={() => handleRow(r)}
                    className={cn(isCurrent && "row-current", isSelected && "sel")}
                    style={{ cursor: "pointer", ...(isCurrent ? { background: "var(--iris-dim, rgba(120,120,255,0.08))" } : {}) }}
                    title="Open this strategy"
                  >
                    <td>
                      {num !== undefined ? <span className="strat-num" title={`Algorithm #${num}`}>#{num}</span> : null}
                      {r.strategy_name}
                      {r.kind === "llm" ? <span className="badge badge-iris" style={{ marginLeft: 6 }}>LLM</span> : null}
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
            {rangeFrom.toLocaleString()}–{rangeTo.toLocaleString()} of {filtered.length.toLocaleString()}
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

      <SheetPanel id={selectedId} onClose={() => setSelectedId(null)} />
    </>
  );
}

// ── the right detail sheet — fetches the full Version detail client-side (via the same-origin proxy) and renders
// the SHARED StrategySheet. Honest loading + error states. Ported from the OG strategies page (the regression fix). ──
function SheetPanel({ id, onClose }: { id: string | null; onClose: () => void }) {
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
        <StrategySheet strategy={detail} />
      ) : null}
    </SidePanel>
  );
}

// A multi-select dropdown — click the button, search the options, click rows to toggle several. Selected options
// FLOAT TO THE TOP (selected-first, then the rest) so the picks are visible at a glance; each option carries a
// real checkbox. `renderOption`/`formatValue` let a caller show a friendlier label than the raw option value
// (e.g. "#3 momentum" for a strategy, "Paper" for a status lane).
function MultiSelect({
  label,
  options,
  selected,
  onChange,
  renderOption,
  formatValue,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  renderOption?: (o: string) => string;
  formatValue?: (o: string) => string;
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

  // Filter by the rendered label OR the raw value, then SELECTED-FIRST so picks float to the top.
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const matched = options.filter(
      (o) => optLabel(o).toLowerCase().includes(needle) || o.toLowerCase().includes(needle),
    );
    return matched.slice().sort((a, b) => {
      const sa = selected.has(a) ? 0 : 1;
      const sb = selected.has(b) ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return optLabel(a).localeCompare(optLabel(b));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options, q, selected, renderOption]);

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
