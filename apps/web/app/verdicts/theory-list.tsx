"use client";

// The machine's experiment memory, made glanceable. Each row is one theory the Gate ruled on:
// plain-language hypothesis, source, asset, verdict badge, a deflated-Sharpe gauge against the
// 0.95 bar, and the holdout dSR — with an honest "decays out-of-sample" tag when an in-sample edge
// did not survive the holdout, and a plain-language kill-reason for every FAIL. Expand a theory to
// see its candidate cohort and per-candidate kill-reasons.
//
// Client component: search + source/verdict filters + sort + per-row expand are all local state.
// Renders only the values it is handed (honesty contract) — never pads a series or invents a number.

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type { ExperimentCandidate, ExperimentTheory } from "@/app/data";
import { Badge } from "@/components/ui/badge";
import { GaugeBar } from "@/components/ui/viz";
import { EmptyState } from "@/components/ui/honest-state";
import { SearchInput } from "@/components/ui/input";
import { KillReasonChip, killReasonLabel } from "@/components/theories/kill-reason";
import { cn } from "@/lib/utils";

// The Gate's bar for a real, multiple-testing-survived edge.
const DSR_BAR = 0.95;

type VerdictFilter = "all" | "PASS" | "FAIL" | "decayed";
type SortKey = "recent" | "best" | "worst";

function fmtDsr(v: number | null | undefined): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? v.toFixed(2) : "—";
}

// A theory "decays out-of-sample" when it looked promising in-sample (high dSR) but the holdout
// turned negative. This is the single most important honesty signal on the page.
function decaysOutOfSample(t: ExperimentTheory): boolean {
  return (
    t.best_holdout_dsr !== null &&
    Number.isFinite(t.best_holdout_dsr) &&
    t.best_holdout_dsr < 0 &&
    t.best_dsr >= 0.5
  );
}

// The dominant kill-reason for a FAILed theory: the first reason on its best (highest-dSR) killed
// candidate, surfaced inline so a glance tells the operator WHY the theory died. Decay is reported
// separately by its own tag, so we don't double-count it here.
function topKillReason(t: ExperimentTheory): string | null {
  if (t.decision === "PASS") return null;
  const killed = t.candidates.filter((c) => !c.promoted && c.reasons.length > 0);
  if (killed.length === 0) return null;
  const best = killed.reduce((a, b) =>
    b.deflated_sharpe_prob > a.deflated_sharpe_prob ? b : a
  );
  return best.reasons[0] ?? null;
}

// ─── dSR gauge ────────────────────────────────────────────────────────────────
// In-sample deflated-Sharpe probability against the 0.95 Gate bar. The marker sits at the bar so
// the operator sees at a glance how far short (or past) the threshold a theory landed.
function DsrGauge({ value, passed }: { value: number; passed: boolean }) {
  const clamped = Number.isFinite(value) ? value : 0;
  return (
    <div className="flex items-center gap-2">
      <GaugeBar
        value={clamped}
        max={1}
        marker={DSR_BAR}
        tone={passed ? "up" : "muted"}
        height={6}
        className="w-20"
      />
      <span className={cn("tabular text-[12px]", passed ? "text-up" : "text-muted")}>
        {fmtDsr(clamped)}
      </span>
    </div>
  );
}

function HoldoutCell({ theory }: { theory: ExperimentTheory }) {
  const decays = decaysOutOfSample(theory);
  if (theory.best_holdout_dsr === null) {
    return <span className="tabular text-[12px] text-quiet">no holdout</span>;
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={cn(
          "tabular text-[12px]",
          theory.best_holdout_dsr < 0 ? "text-down" : "text-foreground"
        )}
      >
        {fmtDsr(theory.best_holdout_dsr)}
      </span>
      {decays ? <Badge variant="warn">decays out-of-sample</Badge> : null}
    </div>
  );
}

// ─── Candidate row (expanded) ───────────────────────────────────────────────────
function CandidateRow({ c }: { c: ExperimentCandidate }) {
  const passedBar = c.deflated_sharpe_prob >= DSR_BAR;
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border border-border/50 bg-surface-2/25 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[12.5px] font-medium text-foreground">
            {c.label ?? c.id}
          </span>
          {c.promoted ? (
            <Badge variant="up">promoted</Badge>
          ) : (
            <Badge variant="muted">killed</Badge>
          )}
        </div>
        {c.reasons.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {c.reasons.map((r) => (
              <KillReasonChip key={r} reason={r} />
            ))}
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-4 text-[11.5px]">
        <div className="flex flex-col items-end">
          <span className="text-[10px] uppercase tracking-wide text-quiet">dSR</span>
          <span className={cn("tabular", passedBar ? "text-up" : "text-muted")}>
            {fmtDsr(c.deflated_sharpe_prob)}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[10px] uppercase tracking-wide text-quiet">holdout</span>
          <span
            className={cn(
              "tabular",
              c.holdout_deflated_sharpe !== null && c.holdout_deflated_sharpe < 0
                ? "text-down"
                : "text-foreground"
            )}
          >
            {c.holdout_deflated_sharpe === null ? "—" : fmtDsr(c.holdout_deflated_sharpe)}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[10px] uppercase tracking-wide text-quiet">FDR</span>
          <span className={cn("tabular", c.survived_fdr ? "text-up" : "text-quiet")}>
            {c.survived_fdr ? "survived" : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Theory row ─────────────────────────────────────────────────────────────────
function TheoryRow({ theory }: { theory: ExperimentTheory }) {
  const [open, setOpen] = useState(false);
  const passed = theory.decision === "PASS";
  const date = theory.ts ? theory.ts.slice(0, 10) : "";
  const hasCandidates = theory.candidates.length > 0;
  const killReason = topKillReason(theory);

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2.5">
        <button
          type="button"
          onClick={() => hasCandidates && setOpen((v) => !v)}
          aria-expanded={hasCandidates ? open : undefined}
          className={cn(
            "flex min-w-0 flex-1 items-start gap-2 text-left",
            hasCandidates && "cursor-pointer"
          )}
        >
          {hasCandidates ? (
            <span className="mt-0.5 shrink-0 text-quiet">
              {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </span>
          ) : (
            <span className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13.5px] font-medium leading-snug text-foreground">
                {theory.hypothesis}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-quiet">
              <span className="capitalize">{theory.source}</span>
              {theory.asset ? <span className="tabular text-muted">{theory.asset}</span> : null}
              <span>{theory.kind.replace(/[-_]/g, " ")}</span>
              {date ? <span className="tabular">{date}</span> : null}
              <span className="tabular">
                {theory.n_promoted}/{theory.n_candidates} promoted
              </span>
            </div>
            {/* The plain-language reason this theory died, surfaced on the row itself — the failure
                is the legible product, not something buried behind an expand. */}
            {killReason ? (
              <div className="mt-1.5 text-[11.5px] leading-snug text-muted">
                <span className="text-quiet">Killed: </span>
                <span className="text-down/90">{killReasonLabel(killReason)}</span>
              </div>
            ) : null}
          </div>
        </button>

        <div className="flex shrink-0 items-center gap-5">
          <div className="flex flex-col items-end gap-1">
            <span className="text-[10px] uppercase tracking-wide text-quiet">dSR vs 0.95</span>
            <DsrGauge value={theory.best_dsr} passed={passed} />
          </div>
          <div className="flex flex-col items-end gap-1">
            <span className="text-[10px] uppercase tracking-wide text-quiet">holdout</span>
            <HoldoutCell theory={theory} />
          </div>
          <Badge variant={passed ? "up" : "muted"} className="mt-0.5">
            {passed ? "PASS" : "FAIL"}
          </Badge>
        </div>
      </div>

      {open && hasCandidates ? (
        <div className="mt-3 space-y-2 pl-[22px]">
          <div className="text-[10.5px] font-semibold uppercase tracking-wide text-quiet">
            Cohort · {theory.candidates.length} candidate{theory.candidates.length === 1 ? "" : "s"}
          </div>
          {theory.candidates.map((c) => (
            <CandidateRow key={c.id} c={c} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

// ─── List ─────────────────────────────────────────────────────────────────────
export function TheoryList({
  theories,
  sources
}: {
  theories: ExperimentTheory[];
  sources: string[];
}) {
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState<VerdictFilter>("all");
  const [source, setSource] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("recent");

  const decayedTotal = useMemo(
    () => theories.filter(decaysOutOfSample).length,
    [theories]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = theories.filter((t) => {
      if (verdict === "decayed") {
        if (!decaysOutOfSample(t)) return false;
      } else if (verdict !== "all" && t.decision !== verdict) {
        return false;
      }
      if (source !== "all" && t.source !== source) return false;
      if (!q) return true;
      const reason = topKillReason(t);
      return (
        t.hypothesis.toLowerCase().includes(q) ||
        t.source.toLowerCase().includes(q) ||
        (t.asset?.toLowerCase().includes(q) ?? false) ||
        t.kind.toLowerCase().includes(q) ||
        (reason ? killReasonLabel(reason).toLowerCase().includes(q) : false)
      );
    });

    const sorted = [...rows];
    if (sort === "best") {
      sorted.sort((a, b) => (b.best_dsr ?? 0) - (a.best_dsr ?? 0));
    } else if (sort === "worst") {
      sorted.sort((a, b) => (a.best_dsr ?? 0) - (b.best_dsr ?? 0));
    } else {
      // recent: ISO timestamps sort lexicographically, newest first.
      sorted.sort((a, b) => (b.ts ?? "").localeCompare(a.ts ?? ""));
    }
    return sorted;
  }, [theories, query, verdict, source, sort]);

  if (theories.length === 0) {
    return (
      <EmptyState
        title="No theories tested yet"
        hint="Every pre-registered hypothesis appears here once the Gate rules on it — PASS or FAIL, with the candidate cohort and kill-reasons. Nothing is fabricated."
        icon={<Search className="size-5" />}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Controls — search + verdict + source + sort. Kept on one calm strip. */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="flex-1 sm:flex-none sm:w-64"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          placeholder="Search hypothesis, asset, reason…"
        />
        <FilterGroup
          options={[
            { value: "all", label: "All" },
            { value: "PASS", label: "Passed" },
            { value: "FAIL", label: "Failed" },
            ...(decayedTotal > 0
              ? [{ value: "decayed", label: "Decayed OOS" }]
              : [])
          ]}
          value={verdict}
          onChange={(v) => setVerdict(v as VerdictFilter)}
        />
        {sources.length > 1 ? (
          <FilterGroup
            options={[
              { value: "all", label: "All sources" },
              ...sources.map((s) => ({ value: s, label: s }))
            ]}
            value={source}
            onChange={setSource}
          />
        ) : null}
        <FilterGroup
          options={[
            { value: "recent", label: "Recent" },
            { value: "best", label: "Best dSR" },
            { value: "worst", label: "Worst dSR" }
          ]}
          value={sort}
          onChange={(v) => setSort(v as SortKey)}
        />
        <span className="ml-auto text-[11.5px] tabular text-quiet">
          {filtered.length.toLocaleString()} theor{filtered.length === 1 ? "y" : "ies"}
          {filtered.length !== theories.length ? ` · of ${theories.length.toLocaleString()}` : ""}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-10 text-center text-[12px] text-quiet">
          No theories match this filter.
        </div>
      ) : (
        <ul className="divide-y divide-border/60">
          {filtered.map((t) => (
            <TheoryRow key={t.run_id} theory={t} />
          ))}
        </ul>
      )}
    </div>
  );
}

// A small segmented filter control, matching the Tabs aesthetic without pulling in a panel.
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
              "shrink-0 rounded-md px-2.5 py-1 text-[12px] font-medium capitalize transition-colors",
              active
                ? "bg-surface text-foreground shadow-card"
                : "text-muted hover:bg-surface-2/60 hover:text-foreground"
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
