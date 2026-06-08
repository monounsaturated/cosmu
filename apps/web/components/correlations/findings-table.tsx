"use client";

// The FINDINGS TABLE — every (feature · source · asset · horizon · IC · n · p · FDR) row the latest
// scan recorded, made sortable/filterable. FDR survivors are highlighted (the candidate hypotheses);
// non-causal controls carry a plain flag so a strong IC there reads as a data-snooping red flag, not
// an edge. This is the dense, money-truth-restrained core of the surface.
//
// Client component: search + survivor/source filters + column sort are all local state. Renders only
// the values it is handed (honesty contract) — never pads a series, never invents a number. The
// numeric visuals are the page-local primitives (correlation-bits) so this table and the heatmap +
// rail above it render identical, calm encodings.

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import type { CorrelationFinding } from "@/app/data";
import { EmptyState } from "@/components/ui/honest-state";
import { SearchInput } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  ColumnLabel,
  FdrPill,
  fmtHorizon,
  fmtN,
  fmtP,
  IcPill,
  isNonCausal,
  NonCausalFlag
} from "./correlation-bits";

type SurvivorFilter = "all" | "survived" | "non-causal";
type SortKey = "ic" | "abs_ic" | "p" | "n" | "feature";
type SortDir = "asc" | "desc";

const DEFAULT_SORT: SortKey = "abs_ic";

function sortValue(f: CorrelationFinding, key: SortKey): number | string {
  switch (key) {
    case "ic":
      return f.ic;
    case "abs_ic":
      return Math.abs(f.ic);
    case "p":
      return f.p;
    case "n":
      return f.n;
    case "feature":
      return f.feature.toLowerCase();
  }
}

export function FindingsTable({
  findings,
  sources
}: {
  findings: CorrelationFinding[];
  sources: string[];
}) {
  const [query, setQuery] = useState("");
  const [survivor, setSurvivor] = useState<SurvivorFilter>("all");
  const [source, setSource] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>(DEFAULT_SORT);
  // |IC|, p, n default to "most-interesting first" (desc for magnitude/n, asc for p).
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const survivorCount = useMemo(() => findings.filter((f) => f.fdr_survived).length, [findings]);
  const nonCausalCount = useMemo(
    () => findings.filter((f) => isNonCausal(f.deflated_note)).length,
    [findings]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = findings.filter((f) => {
      if (survivor === "survived" && !f.fdr_survived) return false;
      if (survivor === "non-causal" && !isNonCausal(f.deflated_note)) return false;
      if (source !== "all" && f.source !== source) return false;
      if (!q) return true;
      return (
        f.feature.toLowerCase().includes(q) ||
        f.source.toLowerCase().includes(q) ||
        f.asset.toLowerCase().includes(q)
      );
    });

    const sorted = [...rows].sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      let cmp: number;
      if (typeof va === "string" && typeof vb === "string") cmp = va.localeCompare(vb);
      else cmp = (va as number) - (vb as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [findings, query, survivor, source, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // p sorts ascending by default (smallest p first); everything else descending.
      setSortDir(key === "p" || key === "feature" ? "asc" : "desc");
    }
  }

  if (findings.length === 0) {
    return (
      <EmptyState
        title="No findings yet"
        hint="Every (feature × asset × horizon) IC the scan records lands here once the sweep runs — with its n, p, and BH-FDR survival. Nothing is fabricated."
        icon={<Search className="size-5" />}
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Controls — search + survivor + source. One calm strip, matching the Theories list. */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="flex-1 sm:flex-none sm:w-64"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          placeholder="Search feature, source, asset…"
        />
        <FilterGroup
          options={[
            { value: "all", label: "All" },
            ...(survivorCount > 0 ? [{ value: "survived", label: `FDR survived · ${survivorCount}` }] : []),
            ...(nonCausalCount > 0 ? [{ value: "non-causal", label: `Non-causal · ${nonCausalCount}` }] : [])
          ]}
          value={survivor}
          onChange={(v) => setSurvivor(v as SurvivorFilter)}
        />
        {sources.length > 1 ? (
          <FilterGroup
            options={[{ value: "all", label: "All sources" }, ...sources.map((s) => ({ value: s, label: s }))]}
            value={source}
            onChange={setSource}
          />
        ) : null}
        <span className="ml-auto text-[11.5px] tabular text-quiet">
          {filtered.length.toLocaleString()} finding{filtered.length === 1 ? "" : "s"}
          {filtered.length !== findings.length ? ` · of ${findings.length.toLocaleString()}` : ""}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-10 text-center text-[12px] text-quiet">
          No findings match this filter.
        </div>
      ) : (
        <Table>
          <THead sticky>
            <TR>
              <SortableTH label="Feature" active={sortKey === "feature"} dir={sortDir} onClick={() => toggleSort("feature")} />
              <TH>Source</TH>
              <TH>Asset</TH>
              <TH className="text-right">Horizon</TH>
              <SortableTH label="IC" active={sortKey === "abs_ic"} dir={sortDir} onClick={() => toggleSort("abs_ic")} align="right" />
              <SortableTH label="n" active={sortKey === "n"} dir={sortDir} onClick={() => toggleSort("n")} align="right" />
              <SortableTH label="p" active={sortKey === "p"} dir={sortDir} onClick={() => toggleSort("p")} align="right" />
              <TH className="text-right">FDR</TH>
            </TR>
          </THead>
          <TBody>
            {filtered.map((f) => {
              const nonCausal = isNonCausal(f.deflated_note);
              return (
                <TR
                  key={`${f.feature}·${f.source}·${f.asset}·${f.horizon}`}
                  className={cn(f.fdr_survived && "bg-up/[0.04]")}
                >
                  <TD>
                    <div className="flex flex-col gap-1">
                      <span className="font-medium text-foreground">{f.feature}</span>
                      {f.deflated_note ? <NonCausalFlag note={f.deflated_note} /> : null}
                    </div>
                  </TD>
                  <TD className="capitalize text-muted">{f.source}</TD>
                  <TD className="tabular text-muted">{f.asset}</TD>
                  <TD className="text-right tabular text-muted">{fmtHorizon(f.horizon)}</TD>
                  <TD className="text-right">
                    <IcPill ic={f.ic} survived={f.fdr_survived} />
                  </TD>
                  <TD className="text-right tabular text-muted">{fmtN(f.n)}</TD>
                  <TD className={cn("text-right tabular", f.p < 0.05 && !nonCausal ? "text-foreground" : "text-quiet")}>
                    {fmtP(f.p)}
                  </TD>
                  <TD className="text-right">
                    <FdrPill survived={f.fdr_survived} />
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </div>
  );
}

// A header cell that toggles sort on click and shows the active direction arrow.
function SortableTH({
  label,
  active,
  dir,
  onClick,
  align = "left"
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: "left" | "right";
}) {
  return (
    <TH className={align === "right" ? "text-right" : undefined}>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-1 rounded outline-none transition-colors hover:text-muted focus-visible:ring-2 focus-visible:ring-ring/40",
          align === "right" && "flex-row-reverse",
          active && "text-foreground"
        )}
        aria-label={`Sort by ${label}`}
      >
        <ColumnLabel>{label}</ColumnLabel>
        {active ? (
          dir === "asc" ? (
            <ArrowUp className="size-3" />
          ) : (
            <ArrowDown className="size-3" />
          )
        ) : null}
      </button>
    </TH>
  );
}

// The segmented filter control, matching the Theories list aesthetic.
function FilterGroup({
  options,
  value,
  onChange
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex gap-1 rounded-lg border border-border/60 bg-surface-2/30 p-1">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            aria-pressed={active}
            className={cn(
              "shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium capitalize outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/40",
              active ? "bg-surface text-foreground shadow-card" : "text-muted hover:bg-surface-2/60 hover:text-foreground"
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
