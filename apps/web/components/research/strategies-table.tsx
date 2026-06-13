"use client";

// module: the unified, faceted Strategies leaderboard (docs/PRODUCT.md Epic B; VISION §1.2, §5). Every
// strategy-version runs on its own standalone $100k track and is ranked by RISK-ADJUSTED % (deflated OOS
// Sharpe), with net % shown prominently. The PRIMARY filter is signal-family — {Social · News/Events ·
// Math/Price · Macro/Positioning · On-chain/Flow} — DERIVED from the features the spec references (engine
// taxonomy.py), never hand-tagged. Orthogonal facets refine it: asset class · venue · timeframe · status
// (lifecycle) · origin · edge-type. Facets compose (AND across facets, OR within a facet) and read REAL
// fields off the leaderboard row. The numeric columns are click-to-sort (the operator picks the lens —
// risk-adjusted score, net %, OOS, PBO, trades-derived); the default is deflated Sharpe, the honest
// house ranking. Nothing fabricated; the honest empty/offline states live on the page.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, ArrowUpDown, Filter, X } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { SearchInput } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { GaugeBar, SignedBar } from "@/components/ui/viz";
import { cn, formatPct } from "@/lib/utils";

// Real maturity threshold (apps/engine PAPER_MIN_DAYS): a paper track is live-ready at 30 days.
const PAPER_MIN_DAYS = 30;
// Reference scalars for the relative gauges — a deflated Sharpe of ~2 is "strong"; clamp the bar there so
// the visual reads occupancy toward a good score without ever implying a value beyond the real number shown.
const SHARPE_REF = 2;

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
  return "lab";
}
const STATUS_VARIANT: Record<LifeStatus, "warn" | "iris" | "up" | "info" | "down"> = {
  lab: "warn",
  screened: "iris",
  paper: "up",
  live: "info",
  killed: "down"
};

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

// Sortable numeric columns — each maps the operator's chosen lens onto a real row scalar. The default is
// `score` (deflated Sharpe), the honest house ranking. `desc` is the natural reading for every column
// here (biggest score / return / most trades first), so a fresh click on a column starts descending.
type SortKey = "score" | "net" | "oos" | "pbo" | "paper";
const SORT_VALUE: Record<SortKey, (r: LeaderboardRow) => number> = {
  score: (r) => (Number.isFinite(r.deflated_sharpe) ? r.deflated_sharpe : -Infinity),
  net: (r) => r.net_pct,
  oos: (r) => r.track_return_pct,
  pbo: (r) => (Number.isFinite(r.pbo) ? r.pbo : Infinity),
  paper: (r) => r.paper_age_days
};

export function StrategiesTable({ rows, context = "leaderboard" }: { rows: LeaderboardRow[]; context?: "leaderboard" | "paper" }) {
  const router = useRouter();
  // On the Paper surface we surface the FORWARD clock as its own column, so a day-0 track's
  // BACKTEST number can never be misread as paper performance (the operator's flag). The leaderboard
  // keeps its dense ranked view. Either way, the % columns are labelled "Backtest OOS" — never bare "Return".
  const showPaper = context === "paper";
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
  // Sort state — default to the house ranking (deflated Sharpe, descending). Clicking a sortable header
  // selects it descending; clicking the active one flips to ascending; a third click restores the default.
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "score", dir: "desc" });

  // Per-family counts (over the search-filtered rows) for the primary chip row.
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
  // chosen column; ties (and the default) fall back to deflated Sharpe so the order is always stable.
  const filtered = useMemo(() => {
    const result = searched.filter((r) => {
      if (family !== "all" && r.signal_family !== family) return false;
      for (const facet of FACETS) {
        const sel = selected[facet.key];
        if (sel.size > 0 && !sel.has(facet.valueOf(r))) return false;
      }
      return true;
    });
    const value = SORT_VALUE[sort.key];
    const sign = sort.dir === "asc" ? 1 : -1;
    return result.sort((a, b) => {
      const d = value(a) - value(b);
      if (d !== 0) return sign * d;
      return b.deflated_sharpe - a.deflated_sharpe;
    });
  }, [searched, family, selected, sort]);

  // Reference magnitude for the net-% signed bars: the largest |net%| in the filtered cohort, so each bar's
  // length is meaningful RELATIVE to its peers (the digits remain the source of truth).
  const netRef = useMemo(() => Math.max(1, ...filtered.map((r) => Math.abs(r.net_pct))), [filtered]);

  const activeFacetCount = (Object.keys(selected) as FacetKey[]).reduce((n, k) => n + selected[k].size, 0);

  function toggleFacet(key: FacetKey, value: string) {
    setSelected((prev) => {
      const next = new Set(prev[key]);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...prev, [key]: next };
    });
  }

  // Cycle a sortable header: inactive → desc → asc → back to the default (score, desc).
  function toggleSort(key: SortKey) {
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: "desc" };
      if (prev.dir === "desc") return { key, dir: "asc" };
      return { key: "score", dir: "desc" };
    });
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
      {/* Search + filter toggle */}
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
        <span className="ml-auto inline-flex items-center gap-1 text-[11.5px] text-quiet">
          ranked by deflated OOS Sharpe <Tooltip content="The single risk-adjusted ranking scalar (VISION §5). Net % is shown prominently; we rank robustly and show the %." /> · {filtered.length} of {rows.length}
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

      {/* Ranked table */}
      {filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-6 text-center text-[12px] text-quiet">
          No versions match these filters.
        </div>
      ) : (
        <Table>
          <THead>
            <TR>
              <TH className="sticky-col">Version</TH>
              <TH>Family · edge</TH>
              <TH>Status</TH>
              <TH>Class · venue · tf</TH>
              {showPaper ? (
                <SortableTH
                  label="Paper"
                  sortKey="paper"
                  sort={sort}
                  onToggle={toggleSort}
                  tip="Live-data paper test SINCE the Gate funded this track (net of fees). This is the only number that proves the edge holds out-of-sample in real time. A just-funded track reads day 0 / — until it accrues paper history."
                />
              ) : null}
              <SortableTH
                label="Backtest OOS"
                sortKey="oos"
                sort={sort}
                onToggle={toggleSort}
                tip="Out-of-sample backtest return (gross). This is HISTORICAL — it is NOT paper performance. A day-0 paper track still shows its backtest number here."
              />
              <SortableTH label="Net" sortKey="net" sort={sort} onToggle={toggleSort} tip="Net-of-fee return on this Version's standalone track. The signed bar reads sign + size relative to the cohort; the digits are the source of truth." />
              <SortableTH label="Score" sortKey="score" sort={sort} onToggle={toggleSort} tip="Deflated out-of-sample Sharpe — the risk-adjusted house ranking. The gauge fills toward a strong (~2) score." />
              <SortableTH label="PBO" sortKey="pbo" sort={sort} onToggle={toggleSort} tip="Probability of backtest overfitting. Lower is better; the Gate blocks above 0.50." />
            </TR>
          </THead>
          <TBody>
            {filtered.map((row) => {
              const status = lifeStatusOf(row.status);
              return (
                <TR
                  key={row.version_id}
                  className="cursor-pointer transition-colors hover:bg-surface-2/50"
                  onClick={() => router.push(`/strategy/${row.version_id}`)}
                >
                  <TD className="sticky-col">
                    <div className="font-medium text-foreground">{row.name}</div>
                    <div className="truncate text-[11px] text-quiet">
                      {row.features.length > 0 ? row.features.slice(0, 3).join(" · ") : row.lineage}
                      {row.features.length > 3 ? ` +${row.features.length - 3}` : ""}
                    </div>
                  </TD>
                  <TD>
                    <div className="flex flex-wrap items-center gap-1">
                      <Badge variant="iris">{row.signal_family_label}</Badge>
                      <span className="text-[11px] text-quiet">{row.edge_type}</span>
                    </div>
                  </TD>
                  <TD>
                    <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABELS[status]}</Badge>
                  </TD>
                  <TD className="text-[11.5px] text-muted">
                    {row.asset_class} · {row.venue} · {row.timeframe}
                  </TD>
                  {showPaper ? <PaperCell row={row} /> : null}
                  <TD className={cn("text-right tabular", row.track_return_pct >= 0 ? "text-up" : "text-down")}>
                    {formatPct(row.track_return_pct)}
                  </TD>
                  {/* Net % — the figure stays the source of truth; the signed bar makes sign + relative size glanceable. */}
                  <TD className="text-right">
                    <div className={cn("tabular", row.net_pct >= 0 ? "text-up" : "text-down")}>{formatPct(row.net_pct)}</div>
                    <SignedBar value={row.net_pct} max={netRef} className="mt-1 ml-auto w-16" />
                  </TD>
                  {/* Score (deflated Sharpe) + an occupancy gauge toward a strong (~2) score. */}
                  <TD className="text-right">
                    <div className="tabular text-foreground">{Number.isFinite(row.deflated_sharpe) ? row.deflated_sharpe.toFixed(2) : "—"}</div>
                    {Number.isFinite(row.deflated_sharpe) ? (
                      <GaugeBar
                        value={Math.max(0, row.deflated_sharpe)}
                        max={SHARPE_REF}
                        tone={row.deflated_sharpe > 0 ? "iris" : "down"}
                        className="mt-1 ml-auto w-16"
                        height={4}
                      />
                    ) : null}
                  </TD>
                  <TD className="text-right tabular text-muted">{Number.isFinite(row.pbo) ? row.pbo.toFixed(2) : "—"}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </div>
  );
}

// A right-aligned, click-to-sort numeric header. Shows a neutral two-way arrow when inactive and a
// directional arrow (in brand iris) when this column is the active sort — the Linear/Stripe table feel.
function SortableTH({
  label,
  sortKey,
  sort,
  onToggle,
  tip
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; dir: "asc" | "desc" };
  onToggle: (key: SortKey) => void;
  tip: string;
}) {
  const active = sort.key === sortKey;
  return (
    <TH className="text-right">
      <button
        type="button"
        onClick={() => onToggle(sortKey)}
        className={cn(
          "ml-auto inline-flex items-center gap-1 transition-colors hover:text-foreground",
          active ? "text-foreground" : ""
        )}
        aria-label={`Sort by ${label}`}
      >
        {label}
        {active ? (
          sort.dir === "asc" ? (
            <ArrowUp className="size-3 text-iris-soft" />
          ) : (
            <ArrowDown className="size-3 text-iris-soft" />
          )
        ) : (
          <ArrowUpDown className="size-3 opacity-40" />
        )}
      </button>
      <Tooltip content={tip} />
    </TH>
  );
}

// The Paper cell on the Paper surface. HONEST by construction: the leaderboard contract carries the
// paper CLOCK (paper_age_days / live_ready) AND the REAL marked paper return (paper_return_pct —
// net of fees, since funding). We show the live paper % over the day clock; we NEVER borrow the backtest %
// to stand in for paper performance. A just-funded / un-marked track has `paper_return_pct == null`, so it
// reads "day 0 · 0%" (the honest day-0 truth) — never the rosy backtest. A flat/negative marked track shows
// its TRUE (0 / negative) number.
function PaperCell({ row }: { row: LeaderboardRow }) {
  const days = Number.isFinite(row.paper_age_days) ? row.paper_age_days : 0;
  const whole = Math.floor(days);
  // null/undefined = NO marked trajectory yet (day-0 / never marked). Show an honest 0%, NOT the backtest.
  const marked = typeof row.paper_return_pct === "number" && Number.isFinite(row.paper_return_pct);
  const fwd = marked ? (row.paper_return_pct as number) : 0;
  if (days < 1) {
    // Just funded: day 0, no paper history. The % is the honest 0 — never the backtest number.
    return (
      <TD className="text-right">
        <div className="tabular text-quiet">day 0 · {formatPct(fwd)}</div>
        <div className="text-[10.5px] uppercase tracking-wide text-quiet">no paper yet</div>
        <GaugeBar value={0} max={PAPER_MIN_DAYS} tone="muted" className="mt-1 ml-auto w-20" height={4} />
      </TD>
    );
  }
  return (
    <TD className="text-right">
      <div className={cn("tabular", marked ? (fwd >= 0 ? "text-up" : "text-down") : "text-quiet")}>{formatPct(fwd)}</div>
      <div className={cn("text-[10.5px] uppercase tracking-wide", row.live_ready ? "text-up" : "text-quiet")}>
        {whole}d · {row.live_ready ? "matured" : "maturing"}
      </div>
      {/* Paper-age progress toward the 30-day live-ready threshold — the bar reads maturity at a glance. */}
      <GaugeBar
        value={Math.min(whole, PAPER_MIN_DAYS)}
        max={PAPER_MIN_DAYS}
        tone={row.live_ready ? "up" : "iris"}
        className="mt-1 ml-auto w-20"
        height={4}
      />
    </TD>
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
