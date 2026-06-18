"use client";

// module: the Lab per-symbol SCREENER. One row per (strategy × symbol × venue) backtest cell — the granular
// truth the pooled leaderboard averages away — ranked by standalone return so the strongest OUTLIER leads. Each
// row carries the honest cross-symbol VERDICT: robust (corroborated across the tested universe), fragile (a lone
// best-of-N winner — flagged with caution, never celebrated), thin (too few trades to judge), negative. Filter by
// verdict / symbol / venue, search by name or symbol, sort any column. Visibility only — the deterministic Gate
// alone decides funding. Reuses the v18 Iris Bento tokens (.toolbar-row / .chip-row / .screener-wrap / .badge).
//
// HONESTY: return_pct / max_drawdown are stored as FRACTIONS (0.21 = 21%) — multiplied by 100 for display, like
// the leaderboard. The verdict counts symbols as INDEPENDENT, so on correlated majors (BTC~ETH) it can over-state
// "robust"; that caveat is surfaced inline rather than hidden.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { LabSymbolRow } from "@cosmu/contracts-ts";
import { cn, formatPct } from "@/lib/utils";

// The fiche-triplet URL for a cell — the strategy detail page focused on this exact (version, symbol, venue).
// venue_id is carried as "" for a NULL-venue cell so the sibling stays addressable.
export function tripletHref(r: { strategy_version_id: string; symbol: string; venue_id: string | null }): string {
  const qs = new URLSearchParams({ symbol: r.symbol, venue: r.venue_id ?? "" });
  return `/strategy/${r.strategy_version_id}?${qs.toString()}`;
}

// The clicked/current triplet, so the comparison grid can highlight the row the operator is looking at.
export type TripletKey = { strategy_version_id: string; symbol: string; venue_id: string | null };

type VerdictKey = "robust" | "fragile" | "thin" | "negative";
const VERDICT_META: Record<VerdictKey, { label: string; color: string; dim: string }> = {
  robust: { label: "Robust", color: "var(--up)", dim: "var(--up-dim)" },
  fragile: { label: "Fragile", color: "var(--gold)", dim: "var(--gold-dim)" },
  negative: { label: "Negative", color: "var(--down)", dim: "var(--down-dim)" },
  thin: { label: "Thin", color: "var(--ink-2, #8a8a8a)", dim: "transparent" },
};

type FilterKey = "all" | VerdictKey;

type SortKey = "strategy" | "symbol" | "venue" | "return" | "pooled" | "sharpe" | "dd" | "trades" | "verdict";
type SortDir = "asc" | "desc";
const VERDICT_RANK: Record<string, number> = { robust: 3, fragile: 2, negative: 1, thin: 0 };
const SORT_VALUE: Record<SortKey, (r: LabSymbolRow) => number | string> = {
  strategy: (r) => r.strategy_name.toLowerCase(),
  symbol: (r) => r.symbol.toLowerCase(),
  venue: (r) => (r.venue_id ?? "").toLowerCase(),
  return: (r) => r.return_pct,
  // nulls (legacy cells with no parent backtest) sort to the bottom on the default desc.
  pooled: (r) => (r.pooled_return_pct ?? Number.NEGATIVE_INFINITY),
  sharpe: (r) => r.sharpe,
  dd: (r) => r.max_drawdown,
  trades: (r) => r.trades,
  verdict: (r) => VERDICT_RANK[r.verdict ?? "thin"] ?? 0,
};

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  const meta = VERDICT_META[(verdict ?? "thin") as VerdictKey] ?? VERDICT_META.thin;
  if (verdict === "thin" || !verdict) return <span className="quiet">{meta.label}</span>;
  return (
    <span
      className="badge"
      style={{ background: meta.dim, color: meta.color, borderColor: meta.color }}
      title={
        verdict === "fragile"
          ? "Positive on this symbol but the edge does NOT generalize across the tested universe — a lone/minority winner (best-of-N caution)."
          : verdict === "robust"
            ? "Positive here AND the edge generalizes across the tested symbols — corroborated."
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
  title = "Lab",
  caption = true,
  ribbon,
  highlight,
}: {
  rows: LabSymbolRow[];
  symbols: string[];
  venues: string[];
  title?: string;          // the page-title shown in the toolbar row ("Strategies" on the merged surface)
  caption?: boolean;       // the explanatory line under the toolbar — off for the compact comparison grid
  ribbon?: React.ReactNode; // optional money-split ribbon, slotted below the toolbar (v18 order)
  highlight?: TripletKey;  // the current triplet — its row is marked so the operator sees where they are
}) {
  const router = useRouter();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [symbol, setSymbol] = useState<string>("");
  const [venue, setVenue] = useState<string>("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "return", dir: "desc" });

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length, robust: 0, fragile: 0, thin: 0, negative: 0 };
    for (const r of rows) c[r.verdict ?? "thin"] = (c[r.verdict ?? "thin"] ?? 0) + 1;
    return c;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = rows.filter((r) => {
      if (filter !== "all" && (r.verdict ?? "thin") !== filter) return false;
      if (symbol && r.symbol !== symbol) return false;
      if (venue && r.venue_id !== venue) return false;
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
  }, [rows, filter, symbol, venue, query, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "strategy" || key === "symbol" || key === "venue" ? "asc" : "desc" }));
  }

  const HEADERS: { key: SortKey; label: string; align?: "right"; tip?: string }[] = [
    { key: "strategy", label: "Strategy" },
    { key: "symbol", label: "Symbol" },
    { key: "venue", label: "Venue" },
    { key: "return", label: "Return", align: "right", tip: "The granular, standalone net-of-fee return on THIS symbol at THIS venue — the truth, never a pooled mean." },
    { key: "pooled", label: "Pooled (adv.)", align: "right", tip: "pooled (advisory): the parent backtest's pooled OOS return, shown for context only. Advisory — never the per-cell truth, never a verdict input, never funds." },
    { key: "sharpe", label: "Sharpe", align: "right" },
    { key: "dd", label: "Max DD", align: "right" },
    { key: "trades", label: "Trades", align: "right" },
    { key: "verdict", label: "Verdict" },
  ];

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
          <select className="search-input" value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="Filter by symbol" style={{ maxWidth: 130 }}>
            <option value="">All symbols</option>
            {symbols.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select className="search-input" value={venue} onChange={(e) => setVenue(e.target.value)} aria-label="Filter by venue" style={{ maxWidth: 120 }}>
            <option value="">All venues</option>
            {venues.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
          <input className="search-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search strategy or symbol…" aria-label="Search" />
        </div>
      </div>

      {ribbon ? <div style={{ marginBottom: 8 }}>{ribbon}</div> : null}

      {caption ? (
        <p className="quiet" style={{ fontSize: 11, margin: "0 4px 8px" }}>
          Each row is one strategy on one symbol at one venue — the granular triplet, never a pooled mean. Ranked by
          standalone return. The “Pooled (adv.)” column is the parent backtest’s pooled OOS number — advisory context
          only, never the truth. “Robust” means the edge generalised across the symbols tested; “Fragile” is a lone
          winner (best-of-N caution). The deterministic Gate alone decides funding. Click a row to open its triplet.
          Note: the verdict counts symbols as independent, so correlated majors (BTC~ETH) can over-state “Robust”.
        </p>
      ) : null}

      <div className="screener-wrap">
        {filtered.length === 0 ? (
          <p className="quiet" style={{ fontSize: 12, padding: "24px 4px", textAlign: "center" }}>No cells match these filters.</p>
        ) : (
          <table className="screener-table" style={{ minWidth: 860 }}>
            <thead>
              <tr>
                {HEADERS.map((h) => {
                  const active = sort.key === h.key;
                  return (
                    <th key={h.key} onClick={() => toggleSort(h.key)} title={h.tip} style={{ cursor: "pointer", textAlign: h.align ?? "left" }}>
                      <div className="th-inner" style={h.align === "right" ? { justifyContent: "flex-end" } : undefined}>
                        {h.label}
                        <span className={cn("sort-ind", active && (sort.dir === "asc" ? "asc" : "desc"))} />
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => {
                const isCurrent =
                  highlight !== undefined &&
                  highlight.strategy_version_id === r.strategy_version_id &&
                  highlight.symbol === r.symbol &&
                  (highlight.venue_id ?? "") === (r.venue_id ?? "");
                return (
                  <tr
                    key={`${r.strategy_version_id}-${r.symbol}-${r.venue_id ?? ""}-${i}`}
                    onClick={() => router.push(tripletHref(r))}
                    className={isCurrent ? "row-current" : undefined}
                    style={{ cursor: "pointer", ...(isCurrent ? { background: "var(--iris-dim, rgba(120,120,255,0.08))" } : {}) }}
                    title="Open this triplet"
                  >
                    <td>
                      {r.strategy_name}
                      {r.kind === "llm" ? <span className="badge badge-iris" style={{ marginLeft: 6 }}>LLM</span> : null}
                    </td>
                    <td>{r.symbol}</td>
                    <td className={r.venue_id ? undefined : "quiet"}>{r.venue_id ?? "—"}</td>
                    <td style={{ textAlign: "right", color: r.return_pct >= 0 ? "var(--up)" : "var(--down)" }}>{formatPct(r.return_pct * 100)}</td>
                    <td style={{ textAlign: "right" }} className="quiet">
                      {r.pooled_return_pct === null || r.pooled_return_pct === undefined ? "—" : formatPct(r.pooled_return_pct * 100)}
                    </td>
                    <td style={{ textAlign: "right" }}>{Number.isFinite(r.sharpe) ? r.sharpe.toFixed(2) : "—"}</td>
                    <td style={{ textAlign: "right" }} className="quiet">{`${(r.max_drawdown * 100).toFixed(1)}%`}</td>
                    <td style={{ textAlign: "right" }}>{r.trades}</td>
                    <td><VerdictBadge verdict={r.verdict} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
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
