"use client";

// module: strategies list, organized by LIFECYCLE. A Version moves through clear stages —
// Discovering (just authored / screening) → Validating (optimizing on more data) → Forward-test (funded on
// Forward-test → Live (real money) — or it dies (Graveyard). We segment the table by stage so
// the operator can tell at a glance what is new vs. learning vs. proven, with a count + one-line
// plain-language explainer per stage and a stage filter. Within each stage rows rank by Score
// (deflated Sharpe), highest first — no survivor bias, the same honest ranking everywhere.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn, formatPct } from "@/lib/utils";

// Disambiguate the two return columns right where they live.
const TRACK_VS_AGGREGATE = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-foreground">Return</span> — this Version&apos;s raw return on its own track.
    </p>
    <p>
      <span className="font-semibold text-foreground">Net</span> — the same track after fees and costs. Each strategy
      stands on its own — there is no pooled wallet.
    </p>
  </div>
);

// Lifecycle stages, in funnel order. Each engine status maps to exactly one stage.
type Stage = "discovering" | "validating" | "forward_test" | "live" | "graveyard";

const STAGES: { id: Stage; label: string; explainer: string; badge: "warn" | "iris" | "up" | "info" | "down" }[] = [
  {
    id: "discovering",
    label: "Discovering",
    explainer: "Freshly authored — running the deterministic Gate screen. Most won't make it past here.",
    badge: "warn"
  },
  {
    id: "validating",
    label: "Validating",
    explainer: "Cleared the screen — now re-tested on more data to confirm the edge is real, not luck.",
    badge: "iris"
  },
  {
    id: "forward_test",
    label: "Forward-test",
    explainer: "Proving itself on its own track on real prices — no real money, no pooled wallet.",
    badge: "up"
  },
  {
    id: "live",
    label: "Live",
    explainer: "Armed on real capital. Only reachable after the Gate passes and you confirm on Live.",
    badge: "info"
  },
  {
    id: "graveyard",
    label: "Graveyard",
    explainer: "Killed — the edge didn't hold. Kept so the machine (and you) can learn from the deaths.",
    badge: "down"
  }
];

// Map a raw engine status onto a lifecycle stage. Unknown/new statuses default to Discovering so a
// Version is never silently hidden.
function stageOf(status: string | null | undefined): Stage {
  const s = (status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "graveyard";
  if (s === "live") return "live";
  if (s === "forward_test" || s === "paper") return "forward_test";
  if (s === "validating" || s === "optimizing") return "validating";
  // draft, new, screening, screened, and anything else → the entry stage.
  return "discovering";
}

const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  forward_test: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

export function StrategiesTable({ rows }: { rows: LeaderboardRow[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<Stage | "all">("all");

  // Search-filter once, then bucket by stage and rank each bucket by Score (deflated Sharpe) desc.
  const { buckets, counts, totalMatching } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q
      ? rows.filter((r) => r.name.toLowerCase().includes(q) || r.status.toLowerCase().includes(q))
      : rows;

    const buckets: Record<Stage, LeaderboardRow[]> = {
      discovering: [],
      validating: [],
      forward_test: [],
      live: [],
      graveyard: []
    };
    for (const r of matched) buckets[stageOf(r.status)].push(r);
    for (const stage of Object.keys(buckets) as Stage[]) {
      buckets[stage].sort((a, b) => b.deflated_sharpe - a.deflated_sharpe);
    }
    const counts = Object.fromEntries(
      (Object.keys(buckets) as Stage[]).map((s) => [s, buckets[s].length])
    ) as Record<Stage, number>;
    return { buckets, counts, totalMatching: matched.length };
  }, [rows, query]);

  const visibleStages = STAGES.filter((s) => stageFilter === "all" || s.id === stageFilter);

  return (
    <div className="space-y-5">
      {/* Search + stage filter */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-quiet" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search Strategies…"
              className="h-8 w-full rounded-md border border-border bg-background/60 pl-8 pr-2 text-[12.5px] text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
            />
          </div>
          <span className="ml-auto inline-flex items-center gap-1 text-[11.5px] text-quiet">
            Return vs net <Tooltip content={TRACK_VS_AGGREGATE} /> · {totalMatching} Versions
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by lifecycle stage">
          <StageChip label="All stages" count={totalMatching} active={stageFilter === "all"} onClick={() => setStageFilter("all")} />
          {STAGES.map((s) => (
            <StageChip key={s.id} label={s.label} count={counts[s.id]} active={stageFilter === s.id} onClick={() => setStageFilter(s.id)} />
          ))}
        </div>
      </div>

      {/* One segment per stage. Empty stages stay visible (with a calm note) so the funnel reads
          honestly — you can see a stage is empty rather than wondering where it went. */}
      <div className="space-y-6">
        {visibleStages.map((stage) => {
          const stageRows = buckets[stage.id];
          return (
            <section key={stage.id} className="space-y-2.5">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-foreground">
                  <Badge variant={stage.badge}>{stage.label}</Badge>
                  <span className="tabular text-quiet">{stageRows.length}</span>
                </h3>
                <p className="text-[11.5px] leading-snug text-quiet">{stage.explainer}</p>
              </div>

              {stageRows.length === 0 ? (
                <div className="rounded-md border border-dashed border-border/60 px-3 py-3 text-[11.5px] text-quiet">
                  Nothing in {stage.label} yet.
                </div>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH className="sticky-col">Version</TH>
                      <TH>Status</TH>
                      <TH className="text-right">Return</TH>
                      <TH className="text-right">Net</TH>
                      <TH className="text-right">
                        <span className="inline-flex items-center gap-1">Score</span>
                      </TH>
                      <TH className="text-right">PBO</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {stageRows.map((row) => (
                      <TR
                        key={row.version_id}
                        onClick={() => router.push(`/strategy/${row.version_id}`)}
                        className="group cursor-pointer transition-colors hover:bg-surface-2/50"
                      >
                        <TD className="sticky-col group-hover:bg-surface-2/50">
                          <div className="font-medium text-foreground">{row.name}</div>
                          <div className="text-[11px] text-quiet">{row.lineage}</div>
                        </TD>
                        <TD>
                          <Badge variant={statusVariant[(row.status ?? "").toLowerCase()] ?? "muted"}>{row.status ?? "—"}</Badge>
                        </TD>
                        <TD className={`text-right tabular ${row.track_return_pct >= 0 ? "text-up" : "text-down"}`}>
                          {formatPct(row.track_return_pct)}
                        </TD>
                        <TD className={`text-right tabular ${row.net_pct >= 0 ? "text-up" : "text-down"}`}>{formatPct(row.net_pct)}</TD>
                        <TD className="text-right tabular text-foreground">{Number.isFinite(row.deflated_sharpe) ? row.deflated_sharpe.toFixed(2) : "—"}</TD>
                        <TD className="text-right tabular text-muted">{Number.isFinite(row.pbo) ? row.pbo.toFixed(2) : "—"}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function StageChip({
  label,
  count,
  active,
  onClick
}: {
  label: string;
  count: number;
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
      <span className={cn("tabular text-[11px]", active ? "text-iris-soft" : "text-quiet")}>{count}</span>
    </button>
  );
}
