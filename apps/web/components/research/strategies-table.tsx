"use client";

// module: the unified, faceted Strategies leaderboard (docs/PRODUCT.md Epic B; VISION §1.2, §5). Every
// strategy-version runs on its own standalone $100k track and is ranked by RISK-ADJUSTED % (deflated OOS
// Sharpe), with net % shown prominently. The PRIMARY filter is signal-family — {Social · News/Events ·
// Math/Price · Macro/Positioning · On-chain/Flow} — DERIVED from the features the spec references (engine
// taxonomy.py), never hand-tagged. Orthogonal facets refine it: asset class · venue · timeframe · status
// (lifecycle) · origin · edge-type. Facets compose (AND across facets, OR within a facet) and read REAL
// fields off the leaderboard row. Nothing fabricated; the honest empty/offline states live on the page.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Filter, X } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { SearchInput } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn, formatPct } from "@/lib/utils";

// The five signal-families, in a fixed display order (matches the engine taxonomy).
const FAMILIES: { id: string; label: string }[] = [
  { id: "onchain_flow", label: "On-chain/Flow" },
  { id: "macro_positioning", label: "Macro/Positioning" },
  { id: "math_price", label: "Math/Price" },
  { id: "news_events", label: "News/Events" },
  { id: "social", label: "Social" }
];

// Map a raw engine status onto the lifecycle facet {lab → backtest → simulation → live → killed}.
type LifeStatus = "lab" | "screened" | "forward" | "live" | "killed";
const STATUS_LABELS: Record<LifeStatus, string> = {
  lab: "Lab",
  screened: "Backtest",
  forward: "Simulation",
  live: "Live",
  killed: "Killed"
};
function lifeStatusOf(status: string | null | undefined): LifeStatus {
  const s = (status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "killed";
  if (s === "live") return "live";
  if (s === "forward_test" || s === "forward" || s === "paper") return "forward";
  if (s === "screening" || s === "screened" || s === "validating" || s === "optimizing") return "screened";
  return "lab";
}
const STATUS_VARIANT: Record<LifeStatus, "warn" | "iris" | "up" | "info" | "down"> = {
  lab: "warn",
  screened: "iris",
  forward: "up",
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

export function StrategiesTable({ rows, context = "leaderboard" }: { rows: LeaderboardRow[]; context?: "leaderboard" | "simulation" }) {
  const router = useRouter();
  // On the Simulation surface we surface the FORWARD clock as its own column, so a day-0 track's
  // BACKTEST number can never be misread as forward performance (the operator's flag). The leaderboard
  // keeps its dense ranked view. Either way, the % columns are labelled "Backtest OOS" — never bare "Return".
  const showForward = context === "simulation";
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

  // Final filtered + ranked rows: family (single) AND each facet (OR within). Ranked by deflated Sharpe
  // (risk-adjusted), the same honest ranking everywhere.
  const filtered = useMemo(() => {
    const result = searched.filter((r) => {
      if (family !== "all" && r.signal_family !== family) return false;
      for (const facet of FACETS) {
        const sel = selected[facet.key];
        if (sel.size > 0 && !sel.has(facet.valueOf(r))) return false;
      }
      return true;
    });
    return result.sort((a, b) => b.deflated_sharpe - a.deflated_sharpe);
  }, [searched, family, selected]);

  const activeFacetCount = (Object.keys(selected) as FacetKey[]).reduce((n, k) => n + selected[k].size, 0);

  function toggleFacet(key: FacetKey, value: string) {
    setSelected((prev) => {
      const next = new Set(prev[key]);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...prev, [key]: next };
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
              {showForward ? (
                <TH className="text-right">
                  <span className="inline-flex items-center gap-1">
                    Forward
                    <Tooltip content="Live-data forward test SINCE the Gate funded this track (net of fees). This is the only number that proves the edge holds out-of-sample in real time. A just-funded track reads day 0 / — until it accrues forward history." />
                  </span>
                </TH>
              ) : null}
              <TH className="text-right">
                <span className="inline-flex items-center gap-1">
                  Backtest OOS
                  <Tooltip content="Out-of-sample backtest return (gross). This is HISTORICAL — it is NOT forward performance. A day-0 forward track still shows its backtest number here." />
                </span>
              </TH>
              <TH className="text-right">Net</TH>
              <TH className="text-right">Score</TH>
              <TH className="text-right">PBO</TH>
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
                  {showForward ? <ForwardCell row={row} /> : null}
                  <TD className={cn("text-right tabular", row.track_return_pct >= 0 ? "text-up" : "text-down")}>
                    {formatPct(row.track_return_pct)}
                  </TD>
                  <TD className={cn("text-right tabular", row.net_pct >= 0 ? "text-up" : "text-down")}>{formatPct(row.net_pct)}</TD>
                  <TD className="text-right tabular text-foreground">{Number.isFinite(row.deflated_sharpe) ? row.deflated_sharpe.toFixed(2) : "—"}</TD>
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

// The Forward cell on the Simulation surface. HONEST by construction: the leaderboard contract carries the
// forward-test CLOCK (forward_age_days / live_ready) AND the REAL marked forward return (forward_return_pct —
// net of fees, since funding). We show the live forward % over the day clock; we NEVER borrow the backtest %
// to stand in for forward performance. A just-funded / un-marked track has `forward_return_pct == null`, so it
// reads "day 0 · 0%" (the honest day-0 truth) — never the rosy backtest. A flat/negative marked track shows
// its TRUE (0 / negative) number.
function ForwardCell({ row }: { row: LeaderboardRow }) {
  const days = Number.isFinite(row.forward_age_days) ? row.forward_age_days : 0;
  const whole = Math.floor(days);
  // null/undefined = NO marked trajectory yet (day-0 / never marked). Show an honest 0%, NOT the backtest.
  const marked = typeof row.forward_return_pct === "number" && Number.isFinite(row.forward_return_pct);
  const fwd = marked ? (row.forward_return_pct as number) : 0;
  if (days < 1) {
    // Just funded: day 0, no forward history. The % is the honest 0 — never the backtest number.
    return (
      <TD className="text-right tabular">
        <span className="text-quiet">day 0 · {formatPct(fwd)}</span>
        <div className="text-[10.5px] uppercase tracking-wide text-quiet">no forward yet</div>
      </TD>
    );
  }
  return (
    <TD className="text-right tabular">
      <span className={cn(marked ? (fwd >= 0 ? "text-up" : "text-down") : "text-quiet")}>{formatPct(fwd)}</span>
      <div className={cn("text-[10.5px] uppercase tracking-wide", row.live_ready ? "text-up" : "text-quiet")}>
        {whole}d · {row.live_ready ? "matured" : "maturing"}
      </div>
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
