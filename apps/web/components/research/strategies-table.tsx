"use client";

// module: the unified, faceted Strategies SCREENER (v18, docs/PRODUCT.md Epic B; VISION §1.2, §5). Every
// strategy-version runs on its own standalone $100k track and is ranked by RISK-ADJUSTED % (deflated OOS
// Sharpe / "DSR"), with net dollars and % shown alongside. The PRIMARY family filter — {Social · News/Events ·
// Math/Price · Macro/Positioning · On-chain/Flow} — is DERIVED from the features the spec references (engine
// taxonomy.py), never hand-tagged. Orthogonal facets refine it: asset class · venue · timeframe · status ·
// origin · edge-type.
//
// The TABLE itself is a JS-rendered, sortable screener over a COLS config: a column-header click sorts
// (cycling desc → asc → back to the default DSR ranking), and a column PICKER (checkbox menu with
// Reset-to-default) toggles which lenses show. Venue · Fees · Origin are OFF by default. The whole row is
// clickable and opens the per-Version strat sheet (/strategy/{id}); the table scrolls horizontally when wide.
//
// HONESTY CONTRACT (the binding rule): every cell renders ONLY a real field off the leaderboard row. A null
// money field (value_usd / pnl_usd / pnl_pct) reads an explicit "—", NEVER 0. P&L is TWO columns — dollars
// (e.g. +$419) and % (e.g. +21%), each sortable, each coloured up/down. OOS shows the out-of-sample backtest
// return with its window (e.g. "+8.2% · 2.4y"). The leaderboard contract carries no max-drawdown or fee
// field, so we do NOT fabricate one: "Fees" is an opt-in column that reads "—" until the engine carries it.
// Nothing fabricated; the honest empty/offline states live on the page.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Filter, RotateCcw, X } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { SearchInput } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { GaugeBar } from "@/components/ui/viz";
import { cn, formatPct, formatUsd } from "@/lib/utils";

// Real maturity threshold (apps/engine PAPER_MIN_DAYS): a paper track is live-ready at 30 days.
const PAPER_MIN_DAYS = 30;
// Reference scalars for the relative gauges — a deflated Sharpe of ~2 is "strong"; clamp the bar there so
// the visual reads occupancy toward a good score without ever implying a value beyond the real number shown.
const SHARPE_REF = 2;
// The Gate's deflated-Sharpe live-ready threshold (the green line on the DSR gauge) and PBO ceiling.
const DSR_STRONG = 0.95;
const PBO_CEILING = 0.5;

// The five signal-families, in a fixed display order (matches the engine taxonomy).
const FAMILIES: { id: string; label: string }[] = [
  { id: "onchain_flow", label: "On-chain/Flow" },
  { id: "macro_positioning", label: "Macro/Positioning" },
  { id: "math_price", label: "Math/Price" },
  { id: "news_events", label: "News/Events" },
  { id: "social", label: "Social" }
];

// Map a raw engine status onto the lifecycle facet {lab → backtest → paper → live → killed}.
type LifeStatus = "lab" | "screened" | "paper" | "live" | "killed";
const STATUS_LABELS: Record<LifeStatus, string> = {
  lab: "Lab",
  screened: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};
function lifeStatusOf(status: string | null | undefined): LifeStatus {
  const s = (status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "killed";
  if (s === "live") return "live";
  if (s === "paper" || s === "forward_test" || s === "forward") return "paper";
  if (s === "screening" || s === "screened" || s === "validating" || s === "optimizing") return "screened";
  if (s === "queued" || s === "pending") return "lab";
  return "lab";
}
const STATUS_VARIANT: Record<LifeStatus, "warn" | "iris" | "up" | "info" | "down" | "muted"> = {
  lab: "warn",
  screened: "info",
  paper: "iris",
  live: "down", // live = real capital at risk → the strongest signal colour (matches the v18 ribbon LIVE accent)
  killed: "muted"
};
// Pipeline order for the default "Stage" sort (top-to-bottom by lifecycle maturity).
const STAGE_RANK: Record<LifeStatus, number> = { live: 5, paper: 4, screened: 3, lab: 2, killed: 1 };

// Orthogonal facets, each backed by a real field on the row. `valueOf` extracts the facet value.
type FacetKey = "asset_class" | "venue" | "timeframe" | "status" | "origin" | "edge_type";
const FACETS: { key: FacetKey; label: string; valueOf: (r: LeaderboardRow) => string }[] = [
  { key: "asset_class", label: "Asset class", valueOf: (r) => r.asset_class },
  { key: "venue", label: "Venue", valueOf: (r) => r.venue },
  { key: "timeframe", label: "Timeframe", valueOf: (r) => r.timeframe },
  { key: "status", label: "Status", valueOf: (r) => lifeStatusOf(r.status) },
  { key: "origin", label: "Origin", valueOf: (r) => r.origin },
  { key: "edge_type", label: "Edge type", valueOf: (r) => r.edge_type }
];

function facetDisplay(key: FacetKey, value: string): string {
  if (key === "status") return STATUS_LABELS[value as LifeStatus] ?? value;
  return value;
}

// ─── COLS config — the screener's columns, each a lens onto a REAL row field ─────────────────────────
// `key` is the stable id; `sort` (when present) makes the header click-to-sort and supplies the value
// extractor + the natural reading direction. `defaultOn:false` columns start hidden (the v18 opt-ins).
type SortDir = "asc" | "desc";
type ColKey = "name" | "stage" | "life" | "days" | "value" | "pnl" | "pnlpct" | "dsr" | "pbo" | "oos" | "venue" | "fees" | "origin";

type ColDef = {
  key: ColKey;
  label: string;
  pickerLabel?: string; // label shown in the column-picker menu (defaults to `label`)
  align?: "right";
  defaultOn?: boolean; // default true
  // When sortable, `value` returns a number|string|null (null sorts to the bottom regardless of direction),
  // and `dir` is the natural first-click reading (biggest score / most recent first, lowest PBO first).
  sort?: { dir: SortDir; value: (r: LeaderboardRow) => number | string | null };
  tip?: string;
};

const COLS: ColDef[] = [
  { key: "name", label: "Version", sort: { dir: "asc", value: (r) => r.name.toLowerCase() } },
  { key: "stage", label: "Stage", sort: { dir: "desc", value: (r) => STAGE_RANK[lifeStatusOf(r.status)] } },
  { key: "life", label: "Lifecycle" },
  {
    key: "days",
    label: "Days",
    align: "right",
    sort: { dir: "desc", value: (r) => (Number.isFinite(r.paper_age_days) ? r.paper_age_days : null) },
    tip: "Days on a live-data paper track since the Gate funded it. A backtest-only Version has no paper clock yet."
  },
  {
    key: "value",
    label: "Value",
    align: "right",
    sort: { dir: "desc", value: (r) => numOrNull(r.value_usd) },
    tip: "Current mark of this Version's standalone track (its own $100k start, net of fees). Backtest-only Versions have no funded value yet."
  },
  {
    key: "pnl",
    label: "P&L",
    align: "right",
    sort: { dir: "desc", value: (r) => numOrNull(r.pnl_usd) },
    tip: "Net profit/loss in dollars on this Version's standalone track, net of fees. Shown with its % alongside."
  },
  {
    key: "pnlpct",
    label: "P&L %",
    align: "right",
    sort: { dir: "desc", value: (r) => numOrNull(r.pnl_pct) },
    tip: "Net-of-fee return on this Version's track, as a percent."
  },
  {
    key: "dsr",
    label: "DSR",
    align: "right",
    sort: { dir: "desc", value: (r) => (Number.isFinite(r.deflated_sharpe) ? r.deflated_sharpe : null) },
    tip: "Deflated out-of-sample Sharpe — the risk-adjusted house ranking and the default sort. The gauge fills toward a strong (~2) score; the line marks the 0.95 live-ready bar."
  },
  {
    key: "pbo",
    label: "PBO",
    align: "right",
    sort: { dir: "asc", value: (r) => (Number.isFinite(r.pbo) ? r.pbo : null) },
    tip: "Probability of backtest overfitting. Lower is better; the Gate blocks above 0.50 (shown in gold near the ceiling)."
  },
  {
    key: "oos",
    label: "OOS",
    align: "right",
    sort: { dir: "desc", value: (r) => (Number.isFinite(r.track_return_pct) ? r.track_return_pct : null) },
    tip: "Out-of-sample backtest return (gross), with its window (e.g. 2.4y). HISTORICAL — this is NOT paper performance."
  },
  { key: "venue", label: "Venue", defaultOn: false, sort: { dir: "asc", value: (r) => r.venue } },
  {
    key: "fees",
    label: "Fees",
    pickerLabel: "Fees paid",
    align: "right",
    defaultOn: false,
    tip: "Cumulative fees paid on this track. The leaderboard contract does not yet carry a per-Version fee total, so this reads an honest — until the engine surfaces it."
  },
  { key: "origin", label: "Origin", defaultOn: false, sort: { dir: "asc", value: (r) => r.origin } }
];

function numOrNull(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const DEFAULT_VISIBLE: Record<ColKey, boolean> = COLS.reduce(
  (acc, c) => ({ ...acc, [c.key]: c.defaultOn !== false }),
  {} as Record<ColKey, boolean>
);

export function StrategiesTable({ rows, context = "leaderboard" }: { rows: LeaderboardRow[]; context?: "leaderboard" | "paper" }) {
  void context; // the screener layout is identical on both surfaces; kept for call-site compatibility
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState<string | "all">("all");
  // Each orthogonal facet holds a set of selected values (empty = no constraint).
  const [selected, setSelected] = useState<Record<FacetKey, Set<string>>>(() => ({
    asset_class: new Set(),
    venue: new Set(),
    timeframe: new Set(),
    status: new Set(),
    origin: new Set(),
    edge_type: new Set()
  }));
  const [showFilters, setShowFilters] = useState(false);
  // Column visibility (the picker) — starts at the v18 default view; Reset restores it.
  const [visible, setVisible] = useState<Record<ColKey, boolean>>(() => ({ ...DEFAULT_VISIBLE }));
  const [showCols, setShowCols] = useState(false);
  // Sort state — default to the house ranking (deflated Sharpe, descending). Clicking a sortable header
  // selects it in its natural direction; clicking the active one flips; a third click restores the default.
  const [sort, setSort] = useState<{ key: ColKey; dir: SortDir }>({ key: "dsr", dir: "desc" });

  // Close the column picker on an outside click (the v18 menu behaviour).
  const colWrapRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showCols) return;
    function onDoc(e: MouseEvent) {
      if (colWrapRef.current && !colWrapRef.current.contains(e.target as Node)) setShowCols(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showCols]);

  // Search scope (name / feature / edge) — drives the per-family chip counts.
  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.features.some((f) => f.toLowerCase().includes(q)) ||
        r.edge_type.toLowerCase().includes(q)
    );
  }, [rows, query]);

  const familyCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of searched) counts[r.signal_family] = (counts[r.signal_family] ?? 0) + 1;
    return counts;
  }, [searched]);

  // Available facet values (from the search + family scope), so we never offer an empty facet.
  const facetValues = useMemo(() => {
    const scope = family === "all" ? searched : searched.filter((r) => r.signal_family === family);
    const out: Record<FacetKey, string[]> = {
      asset_class: [],
      venue: [],
      timeframe: [],
      status: [],
      origin: [],
      edge_type: []
    };
    for (const facet of FACETS) {
      const set = new Set<string>();
      for (const r of scope) set.add(facet.valueOf(r));
      out[facet.key] = [...set].filter((v) => v && v !== "—").sort();
    }
    return out;
  }, [searched, family]);

  // Final filtered + sorted rows: family (single) AND each facet (OR within). Sorted by the operator's
  // chosen column; nulls sink to the bottom; ties (and the default) fall back to DSR so order is stable.
  const filtered = useMemo(() => {
    const result = searched.filter((r) => {
      if (family !== "all" && r.signal_family !== family) return false;
      for (const facet of FACETS) {
        const sel = selected[facet.key];
        if (sel.size > 0 && !sel.has(facet.valueOf(r))) return false;
      }
      return true;
    });
    const col = COLS.find((c) => c.key === sort.key);
    const getter = col?.sort?.value;
    const sign = sort.dir === "asc" ? 1 : -1;
    return result.slice().sort((a, b) => {
      if (getter) {
        const va = getter(a);
        const vb = getter(b);
        // Nulls always sink, regardless of direction (an honest "no value yet" never tops the table).
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
  }, [searched, family, selected, sort]);

  // Reference magnitude for the P&L signed-tone read — kept implicit; the digits are the source of truth.
  const activeFacetCount = (Object.keys(selected) as FacetKey[]).reduce((n, k) => n + selected[k].size, 0);
  const visibleCols = COLS.filter((c) => visible[c.key]);

  function toggleFacet(key: FacetKey, value: string) {
    setSelected((prev) => {
      const next = new Set(prev[key]);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...prev, [key]: next };
    });
  }

  // Cycle a sortable header: inactive → its natural dir → flip → back to the default (DSR, desc).
  function toggleSort(col: ColDef) {
    if (!col.sort) return;
    setSort((prev) => {
      if (prev.key !== col.key) return { key: col.key, dir: col.sort!.dir };
      const flipped: SortDir = prev.dir === "asc" ? "desc" : "asc";
      // Third click (back to natural dir) restores the house default.
      if (flipped === col.sort!.dir) return { key: "dsr", dir: "desc" };
      return { key: col.key, dir: flipped };
    });
  }

  function toggleCol(key: ColKey) {
    setVisible((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function resetCols() {
    setVisible({ ...DEFAULT_VISIBLE });
  }

  function clearAll() {
    setFamily("all");
    setSelected({
      asset_class: new Set(),
      venue: new Set(),
      timeframe: new Set(),
      status: new Set(),
      origin: new Set(),
      edge_type: new Set()
    });
  }

  return (
    <div className="space-y-4">
      {/* Toolbar: search · facets toggle · column picker · ranking note */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          placeholder="Search name, feature, edge…"
        />
        <button
          type="button"
          onClick={() => setShowFilters((v) => !v)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors",
            showFilters || activeFacetCount > 0
              ? "border-iris/50 bg-iris/10 text-foreground"
              : "border-border/70 bg-surface-2/30 text-muted hover:border-border hover:text-foreground"
          )}
        >
          <Filter className="size-3.5" /> Facets
          {activeFacetCount > 0 ? <span className="tabular text-iris-soft">{activeFacetCount}</span> : null}
        </button>

        {/* Column picker — checkbox menu with Reset-to-default (v18). */}
        <div ref={colWrapRef} className="relative">
          <button
            type="button"
            onClick={() => setShowCols((v) => !v)}
            aria-expanded={showCols}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors",
              showCols
                ? "border-iris/50 bg-iris/10 text-foreground"
                : "border-border/70 bg-surface-2/30 text-muted hover:border-border hover:text-foreground"
            )}
          >
            <Columns3 className="size-3.5" /> Columns
          </button>
          {showCols ? (
            <div className="absolute right-0 z-30 mt-1.5 w-56 rounded-lg border border-border/70 bg-surface-2 p-1.5 shadow-card">
              <div className="flex items-center justify-between px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-quiet">
                Show columns <span className="font-medium normal-case tracking-normal text-quiet/80">click a row</span>
              </div>
              <div className="max-h-72 overflow-y-auto">
                {COLS.map((c) => {
                  // The Version name is the row's identity — always present, never togglable.
                  if (c.key === "name") return null;
                  const on = visible[c.key];
                  return (
                    <button
                      key={c.key}
                      type="button"
                      onClick={() => toggleCol(c.key)}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors",
                        on ? "bg-iris/10 text-foreground" : "text-muted hover:bg-surface-3 hover:text-foreground"
                      )}
                    >
                      <span
                        className={cn(
                          "grid size-3.5 shrink-0 place-items-center rounded border transition-colors",
                          on ? "border-iris bg-iris text-iris-ink" : "border-border-strong"
                        )}
                        aria-hidden
                      >
                        {on ? <CheckMark /> : null}
                      </span>
                      <span className="flex-1">{c.pickerLabel ?? c.label}</span>
                    </button>
                  );
                })}
              </div>
              <div className="my-1.5 h-px bg-hairline" />
              <button
                type="button"
                onClick={resetCols}
                className="inline-flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium text-iris-soft transition-colors hover:bg-surface-3"
              >
                <RotateCcw className="size-3" /> Reset to default view
              </button>
            </div>
          ) : null}
        </div>

        <span className="ml-auto inline-flex items-center gap-1 text-[11.5px] text-quiet">
          ranked by deflated OOS Sharpe
          <Tooltip content="The single risk-adjusted ranking scalar (VISION §5) — the default sort. Net dollars and % are shown alongside; we rank robustly and show the figures." />
          · {filtered.length} of {rows.length}
        </span>
      </div>

      {/* PRIMARY filter — signal-family, derived from referenced features (no manual tagging). */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-quiet">Signal family</div>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by signal family">
          <FilterChip label="All families" count={searched.length} active={family === "all"} onClick={() => setFamily("all")} />
          {FAMILIES.map((f) => (
            <FilterChip
              key={f.id}
              label={f.label}
              count={familyCounts[f.id] ?? 0}
              active={family === f.id}
              onClick={() => setFamily(family === f.id ? "all" : f.id)}
            />
          ))}
        </div>
      </div>

      {/* Orthogonal facets */}
      {showFilters ? (
        <div className="space-y-3 rounded-lg border border-border/60 bg-surface-2/20 p-3.5">
          {FACETS.map((facet) => {
            const values = facetValues[facet.key];
            if (values.length === 0) return null;
            return (
              <div key={facet.key} className="space-y-1.5">
                <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-quiet">{facet.label}</div>
                <div className="flex flex-wrap gap-1.5">
                  {values.map((v) => (
                    <FilterChip
                      key={v}
                      label={facetDisplay(facet.key, v)}
                      active={selected[facet.key].has(v)}
                      onClick={() => toggleFacet(facet.key, v)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          {activeFacetCount > 0 ? (
            <button type="button" onClick={clearAll} className="inline-flex items-center gap-1 text-[11.5px] font-medium text-iris-soft hover:underline">
              <X className="size-3" /> Clear all filters
            </button>
          ) : null}
        </div>
      ) : null}

      {/* Ranked screener — horizontal scroll on overflow (Table wraps in overflow-x-auto). */}
      {filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-6 text-center text-[12px] text-quiet">
          No versions match these filters.
        </div>
      ) : (
        <Table className="min-w-[760px]">
          <THead>
            <TR>
              {visibleCols.map((c) => (
                <HeaderCell key={c.key} col={c} sort={sort} onToggle={toggleSort} />
              ))}
            </TR>
          </THead>
          <TBody>
            {filtered.map((row, i) => {
              const status = lifeStatusOf(row.status);
              const dimmed = status === "killed" || status === "lab" || status === "screened";
              return (
                <TR
                  // Defensive unique key: the leaderboard can carry the same version_id twice (a Version with
                  // >1 backtest fans out the JOIN); index-suffix so React never collides/omits a row. The
                  // engine-side dedup is the root fix.
                  key={`${row.version_id}-${i}`}
                  className={cn("cursor-pointer transition-colors hover:bg-surface-2/50", dimmed && "opacity-65")}
                  onClick={() => router.push(`/strategy/${row.version_id}`)}
                >
                  {visibleCols.map((c) => (
                    <TD key={c.key} className={cn(c.align === "right" && "text-right", "whitespace-nowrap")}>
                      <Cell col={c.key} row={row} status={status} />
                    </TD>
                  ))}
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </div>
  );
}

// Stable tie-break: a higher deflated Sharpe ranks first (the house default), with nulls last.
function tieByDsr(a: LeaderboardRow, b: LeaderboardRow): number {
  const da = Number.isFinite(a.deflated_sharpe) ? a.deflated_sharpe : -Infinity;
  const db = Number.isFinite(b.deflated_sharpe) ? b.deflated_sharpe : -Infinity;
  return db - da;
}

// A click-to-sort table header. Neutral two-way arrow when inactive; a directional iris arrow when active.
function HeaderCell({
  col,
  sort,
  onToggle
}: {
  col: ColDef;
  sort: { key: ColKey; dir: SortDir };
  onToggle: (col: ColDef) => void;
}) {
  const active = sort.key === col.key;
  const inner = (
    <span className={cn("inline-flex items-center gap-1", col.align === "right" && "ml-auto")}>
      {col.label}
      {col.sort ? (
        active ? (
          sort.dir === "asc" ? (
            <ArrowUp className="size-3 text-iris-soft" />
          ) : (
            <ArrowDown className="size-3 text-iris-soft" />
          )
        ) : (
          <ArrowUpDown className="size-3 opacity-40" />
        )
      ) : null}
      {col.tip ? <Tooltip content={col.tip} /> : null}
    </span>
  );
  return (
    <TH className={cn(col.align === "right" && "text-right")}>
      {col.sort ? (
        <button
          type="button"
          onClick={() => onToggle(col)}
          aria-label={`Sort by ${col.label}`}
          className={cn(
            "inline-flex items-center gap-1 transition-colors hover:text-foreground",
            col.align === "right" && "ml-auto",
            active && "text-foreground"
          )}
        >
          {inner}
        </button>
      ) : (
        inner
      )}
    </TH>
  );
}

// A single screener cell — renders ONLY the real field for `col`, with the honest "—" for null money.
function Cell({ col, row, status }: { col: ColKey; row: LeaderboardRow; status: LifeStatus }) {
  switch (col) {
    case "name":
      return (
        <div>
          <div className="font-medium text-foreground">{row.name}</div>
          <div className="truncate text-[11px] text-quiet">
            {row.features.length > 0 ? row.features.slice(0, 3).join(" · ") : row.lineage}
            {row.features.length > 3 ? ` +${row.features.length - 3}` : ""}
          </div>
        </div>
      );
    case "stage":
      return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABELS[status]}</Badge>;
    case "life":
      return <LifecycleGlyph status={status} />;
    case "days": {
      const days = Number.isFinite(row.paper_age_days) ? Math.floor(row.paper_age_days) : 0;
      if (days <= 0) return <Dash />;
      return (
        <div className="ml-auto w-fit">
          <span className={cn("tabular", row.live_ready ? "text-up" : "text-foreground")}>{days}d</span>
          <GaugeBar
            value={Math.min(days, PAPER_MIN_DAYS)}
            max={PAPER_MIN_DAYS}
            tone={row.live_ready ? "up" : "iris"}
            className="mt-1 w-14"
            height={3}
          />
        </div>
      );
    }
    case "value": {
      const v = numOrNull(row.value_usd);
      return v === null ? <Dash /> : <span className="tabular text-foreground">{formatUsd(v)}</span>;
    }
    case "pnl": {
      const v = numOrNull(row.pnl_usd);
      if (v === null) return <Dash />;
      return <span className={cn("tabular font-medium", v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted")}>{signedUsd(v)}</span>;
    }
    case "pnlpct": {
      const v = numOrNull(row.pnl_pct);
      if (v === null) return <Dash />;
      return <span className={cn("tabular", v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted")}>{formatPct(v, 0)}</span>;
    }
    case "dsr": {
      const dsr = Number.isFinite(row.deflated_sharpe) ? row.deflated_sharpe : null;
      if (dsr === null) return <Dash />;
      return (
        <div className="ml-auto w-fit">
          <span className="tabular text-foreground">{dsr.toFixed(2)}</span>
          <GaugeBar
            value={Math.max(0, dsr)}
            max={SHARPE_REF}
            marker={DSR_STRONG / SHARPE_REF}
            tone={dsr >= DSR_STRONG ? "up" : dsr > 0 ? "iris" : "down"}
            className="mt-1 w-14"
            height={4}
          />
        </div>
      );
    }
    case "pbo": {
      const pbo = Number.isFinite(row.pbo) ? row.pbo : null;
      if (pbo === null) return <Dash />;
      return <span className={cn("tabular", pbo > PBO_CEILING - 0.05 ? "text-gold" : "text-muted")}>{pbo.toFixed(2)}</span>;
    }
    case "oos": {
      const oos = Number.isFinite(row.track_return_pct) ? row.track_return_pct : null;
      if (oos === null) return <Dash />;
      const win = formatWindow(row.oos_window_days);
      return (
        <div className="ml-auto w-fit leading-tight">
          <span className={cn("tabular", oos >= 0 ? "text-up" : "text-down")}>{formatPct(oos, 1)}</span>
          {win ? <div className="text-[10px] tabular text-quiet">{win}</div> : null}
        </div>
      );
    }
    case "venue":
      return <span className="text-[11.5px] text-muted">{row.venue || "—"}</span>;
    case "fees":
      // No per-Version fee total on the leaderboard contract — render an honest "—", never a fabricated cost.
      return <Dash />;
    case "origin":
      return <span className="text-[11px] capitalize text-muted">{row.origin || "—"}</span>;
    default:
      return null;
  }
}

function Dash() {
  return <span className="text-quiet">—</span>;
}

// "+$419" / "-$81" — always a $ on dollar P&L, signed.
function signedUsd(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}${formatUsd(Math.abs(v))}`;
}

// Compact OOS window from days: "2.4y" / "18mo" / "9mo". null/absent → "" (the OOS % shows without a window).
function formatWindow(days: number | null | undefined): string {
  if (typeof days !== "number" || !Number.isFinite(days) || days <= 0) return "";
  if (days >= 365) return `${(days / 365).toFixed(1)}y`;
  const months = Math.round(days / 30);
  if (months >= 1) return `${months}mo`;
  return `${Math.round(days)}d`;
}

// A tiny 3-node lifecycle glyph (Backtest → Paper → Live) — the v18 "Lifecycle" cell, reading the row's
// real stage. Filled nodes = stages reached; the current stage glows; killed shows a red final node.
function LifecycleGlyph({ status }: { status: LifeStatus }) {
  // node states: "done" | "cur" | "off" | "dead"
  let nodes: ("done" | "cur" | "off" | "dead")[];
  if (status === "live") nodes = ["done", "done", "cur"];
  else if (status === "paper") nodes = ["done", "cur", "off"];
  else if (status === "screened") nodes = ["cur", "off", "off"];
  else if (status === "killed") nodes = ["done", "dead", "off"];
  else nodes = ["off", "off", "off"]; // lab / queued
  const dotClass = (n: "done" | "cur" | "off" | "dead") =>
    n === "done"
      ? "bg-iris border-iris"
      : n === "cur"
      ? "bg-iris border-iris ring-2 ring-iris/25"
      : n === "dead"
      ? "bg-down border-down"
      : "bg-surface-3 border-border";
  return (
    <span className="inline-flex items-center gap-1" aria-label={`lifecycle ${status}`}>
      {nodes.map((n, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          <span className={cn("size-1.5 rounded-full border", dotClass(n))} aria-hidden />
          {i < nodes.length - 1 ? (
            <span className={cn("h-px w-2", nodes[i] === "done" ? "bg-iris" : "bg-border")} aria-hidden />
          ) : null}
        </span>
      ))}
    </span>
  );
}

function CheckMark() {
  return (
    <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M2.5 6.5 L5 9 L9.5 3.5" />
    </svg>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium transition-colors",
        active
          ? "border-iris/50 bg-iris/10 text-foreground"
          : "border-border/70 bg-surface-2/30 text-muted hover:border-border hover:bg-surface-2/55 hover:text-foreground"
      )}
    >
      {label}
      {count !== undefined ? <span className={cn("tabular text-[11px]", active ? "text-iris-soft" : "text-quiet")}>{count}</span> : null}
    </button>
  );
}
