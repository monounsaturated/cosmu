"use client";

// module: the Strategies SCREENER — one row per (algorithm × asset × venue) TRIPLET, never pooled. Each row is a
// strategy on one symbol at one venue, ranked by standalone net-of-fee return. Carries the honest per-symbol
// VERDICT: robust (edge generalizes across the tested symbols), fragile (a lone best-of-N winner — caution), thin
// (too few trades to judge), negative (a loser). Restores the OG strategies-page UX on the granular rows: row
// click → right SIDE PANEL with the full strategy sheet; a COLUMN PICKER; the DARK-MODE toggle; plus multi-select
// symbol/venue filters (search + click to pick several). Visibility only — the deterministic Gate alone funds.
//
// HONESTY: return_pct / max_drawdown are stored as FRACTIONS (0.21 = 21%) → ×100 for display. The verdict counts
// symbols as INDEPENDENT, so on correlated majors (BTC~ETH) it can over-state "robust"; surfaced in the caption.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { LabSymbolRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { SidePanel } from "@/components/ui/side-panel";
import { StrategySheet } from "@/components/strategy/strategy-sheet";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { engineGetJson, enginePeek } from "@/lib/engine";
import { cn, formatPct } from "@/lib/utils";

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

type FilterKey = "all" | VerdictKey;

// Sortable column keys. "strategy" is the identity column (always shown); the rest are pickable.
type ColKey = "symbol" | "venue" | "return" | "sharpe" | "dd" | "trades" | "verdict";
type SortKey = "strategy" | ColKey;
type SortDir = "asc" | "desc";

const VERDICT_RANK: Record<string, number> = { robust: 3, fragile: 2, negative: 1, thin: 0 };
const SORT_VALUE: Record<SortKey, (r: LabSymbolRow) => number | string> = {
  strategy: (r) => r.strategy_name.toLowerCase(),
  symbol: (r) => r.symbol.toLowerCase(),
  venue: (r) => (r.venue_id ?? "").toLowerCase(),
  return: (r) => r.return_pct,
  sharpe: (r) => r.sharpe,
  dd: (r) => r.max_drawdown,
  trades: (r) => r.trades,
  verdict: (r) => VERDICT_RANK[r.verdict ?? "thin"] ?? 0,
};

const COLS: { key: ColKey; label: string; align?: "right"; tip?: string }[] = [
  { key: "symbol", label: "Symbol" },
  { key: "venue", label: "Venue" },
  { key: "return", label: "Return", align: "right", tip: "Standalone net-of-fee return on THIS symbol at THIS venue — the truth, never a pooled mean." },
  { key: "sharpe", label: "Sharpe", align: "right" },
  { key: "dd", label: "Max DD", align: "right" },
  { key: "trades", label: "Trades", align: "right" },
  { key: "verdict", label: "Verdict", tip: "robust = edge generalizes across symbols · fragile = lone best-of-N winner · thin = too few trades · negative = loser." },
];
const DEFAULT_VISIBLE: Record<ColKey, boolean> = { symbol: true, venue: true, return: true, sharpe: true, dd: true, trades: true, verdict: true };

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
  const [filter, setFilter] = useState<FilterKey>("all");
  const [symbolSel, setSymbolSel] = useState<Set<string>>(new Set());
  const [venueSel, setVenueSel] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "return", dir: "desc" });
  const [visible, setVisible] = useState<Record<ColKey, boolean>>({ ...DEFAULT_VISIBLE });
  const [showPicker, setShowPicker] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("v"));
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPicker) return;
    const onDoc = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setShowPicker(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showPicker]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length, robust: 0, fragile: 0, thin: 0, negative: 0 };
    for (const r of rows) c[r.verdict ?? "thin"] = (c[r.verdict ?? "thin"] ?? 0) + 1;
    return c;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = rows.filter((r) => {
      if (filter !== "all" && (r.verdict ?? "thin") !== filter) return false;
      if (symbolSel.size && !symbolSel.has(r.symbol)) return false;
      if (venueSel.size && !venueSel.has(r.venue_id ?? "")) return false;
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
  }, [rows, filter, symbolSel, venueSel, query, sort]);

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
      case "verdict":
        return <td key={key}><VerdictBadge verdict={r.verdict} /></td>;
    }
  }

  return (
    <>
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <span className="page-title">{title}</span>
        <div className="chip-row">
          <Chip label="All" count={counts.all} active={filter === "all"} onClick={() => setFilter("all")} />
          <Chip label="Robust" dot="var(--up)" count={counts.robust} active={filter === "robust"} onClick={() => setFilter("robust")} />
          <Chip label="Fragile" dot="var(--gold)" count={counts.fragile} active={filter === "fragile"} onClick={() => setFilter("fragile")} />
          <Chip label="Negative" dot="var(--down)" count={counts.negative} active={filter === "negative"} onClick={() => setFilter("negative")} />
          <Chip label="Thin" count={counts.thin} active={filter === "thin"} onClick={() => setFilter("thin")} />
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <MultiSelect label="symbols" options={symbols} selected={symbolSel} onChange={setSymbolSel} />
          <MultiSelect label="venues" options={venues} selected={venueSel} onChange={setVenueSel} />
          <input className="search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search strategy or symbol…" aria-label="Search" />
          <div className="col-picker-wrap" ref={pickerRef}>
            <button type="button" className="btn-col-picker" onClick={() => setShowPicker((v) => !v)} aria-expanded={showPicker}>Columns</button>
            <div className={cn("col-picker-menu", showPicker && "open")}>
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
      </div>

      {ribbon ? <div style={{ marginBottom: 8 }}>{ribbon}</div> : null}

      {caption ? (
        <p className="quiet" style={{ fontSize: 11, margin: "0 4px 8px" }}>
          Each row is one strategy on one symbol at one venue — the granular triplet, never a pooled mean. Ranked by
          standalone return. “Robust” = the edge generalised across the symbols tested; “Fragile” = a lone winner
          (best-of-N caution); “Thin” = too few trades to judge; “Negative” = a loser. Click a row to open its sheet.
          The deterministic Gate alone decides funding. Note: the verdict counts symbols as independent, so
          correlated majors (BTC~ETH) can over-state “Robust”.
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
              {filtered.map((r, i) => {
                const isCurrent =
                  highlight !== undefined &&
                  highlight.strategy_version_id === r.strategy_version_id &&
                  highlight.symbol === r.symbol &&
                  (highlight.venue_id ?? "") === (r.venue_id ?? "");
                const isSelected = selectedId === r.strategy_version_id;
                return (
                  <tr
                    key={`${r.strategy_version_id}-${r.symbol}-${r.venue_id ?? ""}-${i}`}
                    onClick={() => handleRow(r)}
                    className={cn(isCurrent && "row-current", isSelected && "sel")}
                    style={{ cursor: "pointer", ...(isCurrent ? { background: "var(--iris-dim, rgba(120,120,255,0.08))" } : {}) }}
                    title="Open this strategy"
                  >
                    <td>
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

// A multi-select dropdown with an inline search — click the button, search, click options to toggle several.
function MultiSelect({ label, options, selected, onChange }: { label: string; options: string[]; selected: Set<string>; onChange: (next: Set<string>) => void }) {
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

  const shown = options.filter((o) => o.toLowerCase().includes(q.trim().toLowerCase()));
  const btnLabel = selected.size === 0 ? `All ${label}` : `${selected.size} ${label}`;

  function toggle(o: string) {
    const n = new Set(selected);
    if (n.has(o)) n.delete(o);
    else n.add(o);
    onChange(n);
  }

  return (
    <div className="col-picker-wrap" ref={ref}>
      <button type="button" className={cn("btn-col-picker", selected.size > 0 && "active")} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {btnLabel}
      </button>
      <div className={cn("col-picker-menu", open && "open")} style={{ minWidth: 200 }}>
        <input className="search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${label}…`} style={{ width: "100%", marginBottom: 6 }} />
        {selected.size > 0 ? (
          <div className="col-picker-item" onClick={() => onChange(new Set())}>
            <span className="cp-label">Clear ({selected.size})</span>
          </div>
        ) : null}
        <div style={{ maxHeight: 260, overflowY: "auto" }}>
          {shown.map((o) => (
            <div key={o} className={cn("col-picker-item", selected.has(o) && "on")} onClick={() => toggle(o)}>
              <span className="cp-ind" />
              <span className="cp-label">{o || "—"}</span>
            </div>
          ))}
          {shown.length === 0 ? <p className="quiet" style={{ fontSize: 11, padding: 6 }}>No match.</p> : null}
        </div>
      </div>
    </div>
  );
}

function Chip({ label, count, dot, active, onClick }: { label: string; count?: number; dot?: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={cn("chip", active && "active")} onClick={onClick}>
      {dot ? <span className="chip-dot" style={{ background: dot }} /> : label === "All" ? <span className="chip-dot" /> : null}
      {label}
      {typeof count === "number" ? <span className="quiet" style={{ marginLeft: 4 }}>{count}</span> : null}
    </button>
  );
}
