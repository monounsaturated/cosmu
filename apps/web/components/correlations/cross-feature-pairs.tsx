"use client";

// The CROSS-FEATURE PAIRS PANEL — shows which data sources move together (cross-feature correlation
// findings), making the "crossing" visible: pairs where the machine found that feature A and feature B
// are correlated with each other rather than each independently with a price return.
//
// HOW PAIRS ARE ENCODED: the correlation scan writes a "A~B" feature name (tilde-separated) when it
// measures the IC between one feature series and another feature series rather than against a forward
// return. The asset field carries the asset scope or "MARKET" as usual. This component filters the
// shared /correlations findings for that tilde-encoding and presents them as a dedicated pairs view.
//
// HONESTY CONTRACT: this panel is PROPOSE-ONLY — the same rule as all correlation findings. A strong
// cross-feature IC is a *candidate link*, not a causal mechanism. Non-causal flags are shown plainly.
// The panel renders "no cross-feature findings yet" rather than fabricating a result.
//
// API STATUS: the crossing engine that writes "A~B" feature names is not yet deployed. This component
// is designed to consume the SAME /correlations endpoint shape with a pair filter (feature.includes("~"))
// so it will display real findings the moment the engine starts writing them. In the interim it shows
// an honest "scanning not yet wired" empty state.
//
// CLIENT: search + sort filters are local state; this is a client island.

import { useMemo, useState } from "react";
import { GitBranch, Search } from "lucide-react";
import type { CorrelationFinding } from "@/app/data";
import { EmptyState } from "@/components/ui/honest-state";
import { SearchInput } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  FdrPill,
  fmtHorizon,
  fmtN,
  fmtP,
  IcPill,
  NonCausalFlag
} from "./correlation-bits";

// ── Pair parsing ─────────────────────────────────────────────────────────────────────────────────
// "A~B" → { a: "A", b: "B" }. Returns null when the feature field is not a pair.
function parsePair(feature: string): { a: string; b: string } | null {
  const idx = feature.indexOf("~");
  if (idx < 1 || idx >= feature.length - 1) return null;
  return { a: feature.slice(0, idx), b: feature.slice(idx + 1) };
}

// A lag/lead label derived from the horizon: h=0 = contemporaneous, h>0 = A leads B by h bars.
// When the finding was recorded against a forward return that interpretation is already established;
// for cross-feature findings we surface the lag plainly.
function lagLabel(horizon: number): string {
  if (horizon === 0) return "contemporaneous";
  if (horizon === 1) return "1-bar lead";
  return `${horizon}-bar lead`;
}

// ── Sort ─────────────────────────────────────────────────────────────────────────────────────────
type SortKey = "abs_ic" | "p" | "n";
type SortDir = "asc" | "desc";

function sortValue(f: CorrelationFinding, key: SortKey): number {
  switch (key) {
    case "abs_ic": return Math.abs(f.ic);
    case "p":      return f.p;
    case "n":      return f.n;
  }
}

// ── PairCard ─────────────────────────────────────────────────────────────────────────────────────
// One pair displayed as a compact card: both feature names, the asset scope, the IC, the lag, and
// the FDR/non-causal status. Cards over a grid — scannable, dense, honest.
function PairCard({ finding }: { finding: CorrelationFinding }) {
  const pair = parsePair(finding.feature)!; // guaranteed by caller
  const nonCausal = finding.non_causal;
  const survived = finding.fdr_survived;

  return (
    <div
      className={cn(
        "rounded-lg border bg-surface-2/20 p-3 transition-colors",
        survived ? "border-up/30 bg-up/[0.03]" : "border-border/60"
      )}
    >
      {/* Pair names */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <span
              className="max-w-[44%] truncate text-[13px] font-medium text-foreground"
              title={pair.a}
            >
              {pair.a}
            </span>
            <span className="shrink-0 text-[11px] font-semibold text-iris-soft">~</span>
            <span
              className="max-w-[44%] truncate text-[13px] font-medium text-foreground"
              title={pair.b}
            >
              {pair.b}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-quiet">
            <span className="tabular text-muted">{finding.asset}</span>
            <span className="tabular">{lagLabel(finding.horizon)}</span>
            {finding.source ? (
              <span className="capitalize">{finding.source}</span>
            ) : null}
          </div>
        </div>
        <IcPill ic={finding.ic} survived={survived} />
      </div>

      {/* Stats row */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px] text-quiet">
        <div className="flex items-center gap-3">
          <span>
            n{" "}
            <span className="tabular font-medium text-muted">{fmtN(finding.n)}</span>
          </span>
          <span>
            p{" "}
            <span
              className={cn(
                "tabular font-medium",
                finding.p < 0.05 && !nonCausal ? "text-foreground" : "text-quiet"
              )}
            >
              {fmtP(finding.p)}
            </span>
          </span>
          <span className="tabular">{fmtHorizon(finding.horizon)}</span>
        </div>
        <FdrPill survived={survived} />
      </div>

      {finding.deflated_note ? (
        <div className="mt-1.5">
          <NonCausalFlag note={finding.deflated_note} />
        </div>
      ) : null}
    </div>
  );
}

// ── CrossFeaturePairsPanel ────────────────────────────────────────────────────────────────────────
export function CrossFeaturePairsPanel({ findings }: { findings: CorrelationFinding[] }) {
  // Filter to pair findings (feature contains "~")
  const pairFindings = useMemo(
    () => findings.filter((f) => parsePair(f.feature) !== null),
    [findings]
  );

  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("abs_ic");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const survivorCount = useMemo(
    () => pairFindings.filter((f) => f.fdr_survived).length,
    [pairFindings]
  );
  const nonCausalCount = useMemo(
    () => pairFindings.filter((f) => f.non_causal).length,
    [pairFindings]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = pairFindings.filter((f) => {
      if (!q) return true;
      return (
        f.feature.toLowerCase().includes(q) ||
        f.source.toLowerCase().includes(q) ||
        f.asset.toLowerCase().includes(q)
      );
    });
    return [...rows].sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      const cmp = va - vb;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [pairFindings, query, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "p" ? "asc" : "desc");
    }
  }

  // No pair findings at all — show the "not yet wired" honest empty state.
  if (pairFindings.length === 0) {
    return (
      <EmptyState
        title="No cross-feature pairs found yet"
        hint={
          <>
            The crossing engine writes pair findings as <code className="rounded bg-surface-2 px-1 py-0.5 text-[10.5px] font-mono">A~B</code> feature names.
            Once the cross-feature scan runs, data-source pairs that move together appear here with
            their lag/lead, IC, and FDR status. Propose-only: the Gate disposes of noise.
          </>
        }
        icon={<GitBranch className="size-5" />}
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="flex-1 sm:flex-none sm:w-64"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          placeholder="Search feature, source, asset…"
        />

        {/* Sort pills */}
        <div className="flex gap-1 rounded-lg border border-border/60 bg-surface-2/30 p-1">
          {(
            [
              { key: "abs_ic" as SortKey, label: "|IC|" },
              { key: "p" as SortKey, label: "p" },
              { key: "n" as SortKey, label: "n" }
            ] as const
          ).map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => toggleSort(key)}
              aria-pressed={sortKey === key}
              className={cn(
                "shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/40",
                sortKey === key
                  ? "bg-surface text-foreground shadow-card"
                  : "text-muted hover:bg-surface-2/60 hover:text-foreground"
              )}
            >
              {label} {sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
            </button>
          ))}
        </div>

        <span className="ml-auto text-[11.5px] tabular text-quiet">
          {filtered.length.toLocaleString()} pair{filtered.length === 1 ? "" : "s"}
          {survivorCount > 0 ? (
            <span className="ml-1.5 text-up">· {survivorCount} survived FDR</span>
          ) : null}
          {nonCausalCount > 0 ? (
            <span className="ml-1.5 text-warn">· {nonCausalCount} non-causal</span>
          ) : null}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-10 text-center text-[12px] text-quiet">
          No pairs match this filter.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((f) => (
            <PairCard
              key={`${f.run_id}·${f.feature}·${f.asset}·${f.horizon}`}
              finding={f}
            />
          ))}
        </div>
      )}

      {/* Footer: framing note */}
      <p className="text-[11.5px] leading-relaxed text-quiet">
        Cross-feature pairs that survived FDR are{" "}
        <span className="text-foreground">candidate co-movements, not causal edges</span>.
        A strong IC between two data sources may reflect a shared driver, not a tradeable link.
        The deterministic Gate disposes of whether any pair translates to a strategy.
      </p>
    </div>
  );
}

