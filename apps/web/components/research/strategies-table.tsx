"use client";

// module: strategies list, organized by LIFECYCLE. A Version moves through clear stages —
// Discovering (just authored / screening) → Validating (optimizing on more data) → Forward-test (funded on
// Forward-test → Live (real money) — or it dies (Graveyard). We segment the table by stage so
// the operator can tell at a glance what is new vs. learning vs. proven, with a count + one-line
// plain-language explainer per stage and a stage filter. Within each stage rows rank by Score
// (deflated Sharpe), highest first — no survivor bias, the same honest ranking everywhere.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, Loader2, Search } from "lucide-react";
import type { LeaderboardRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { fetchStrategyDetail } from "@/app/strategies/actions";
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
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detailCache, setDetailCache] = useState<Record<string, StrategyDetailResponse>>({});
  const [isPending, startTransition] = useTransition();

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
                      <TH className="w-6" />
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
                    {stageRows.map((row) => {
                      const isExpanded = expanded === row.version_id;
                      const detail = detailCache[row.version_id];
                      return (
                        <>
                          <TR
                            key={row.version_id}
                            className="group cursor-pointer transition-colors hover:bg-surface-2/50"
                          >
                            <TD
                              className="w-6 px-1"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (isExpanded) {
                                  setExpanded(null);
                                } else {
                                  setExpanded(row.version_id);
                                  if (!detailCache[row.version_id]) {
                                    startTransition(async () => {
                                      const { strategy, connected } = await fetchStrategyDetail(row.version_id);
                                      if (connected && strategy.version_id) {
                                        setDetailCache((c) => ({ ...c, [row.version_id]: strategy }));
                                      }
                                    });
                                  }
                                }
                              }}
                            >
                              <ChevronRight
                                className={cn(
                                  "size-3.5 text-quiet transition-transform",
                                  isExpanded && "rotate-90"
                                )}
                              />
                            </TD>
                            <TD
                              className="sticky-col group-hover:bg-surface-2/50"
                              onClick={() => router.push(`/strategy/${row.version_id}`)}
                            >
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
                          {isExpanded && (
                            <TR key={`${row.version_id}-detail`}>
                              <TD colSpan={7} className="bg-surface-2/20 px-4 py-3">
                                {isPending && !detail ? (
                                  <div className="flex items-center gap-2 text-[12px] text-quiet">
                                    <Loader2 className="size-3.5 animate-spin" /> Loading spec…
                                  </div>
                                ) : detail ? (
                                  <VersionDetailInline spec={detail.spec} params={detail.params} versionId={row.version_id} />
                                ) : (
                                  <div className="text-[12px] text-quiet">Could not load detail — engine may be offline.</div>
                                )}
                              </TD>
                            </TR>
                          )}
                        </>
                      );
                    })}
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

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function extractFeatures(spec: Record<string, unknown>): string[] {
  const found = new Set<string>();
  const walk = (node: unknown) => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (isRecord(node)) {
      for (const [k, v] of Object.entries(node)) {
        if ((k === "feature" || k === "indicator") && typeof v === "string") found.add(v);
        else walk(v);
      }
    }
  };
  walk(spec.entry);
  walk(spec.exit);
  walk(spec.setup);
  return [...found].sort();
}

function VersionDetailInline({
  spec,
  params,
  versionId,
}: {
  spec: Record<string, unknown>;
  params: Record<string, unknown>;
  versionId: string;
}) {
  const router = useRouter();
  const hasSpec = spec && Object.keys(spec).length > 0;
  if (!hasSpec) {
    return <div className="text-[12px] text-quiet">No spec recorded for this version.</div>;
  }

  const universe = isRecord(spec.universe) ? spec.universe : null;
  const features = extractFeatures(spec);
  const paramSpace = isRecord(spec.param_space) ? spec.param_space : {};
  const fitted = params && Object.keys(params).length > 0 ? params : paramSpace;
  const paramKeys = Object.keys(fitted);

  return (
    <div className="space-y-2.5">
      {typeof spec.rationale === "string" && spec.rationale ? (
        <p className="text-[12px] leading-relaxed text-muted">{spec.rationale}</p>
      ) : null}

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-[12px]">
        {universe ? (
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-quiet">Universe </span>
            <span className="text-foreground">
              {Array.isArray(universe.asset_classes) ? (universe.asset_classes as string[]).join(", ") : "—"}
            </span>
            {Array.isArray(universe.venues) && universe.venues.length > 0 && (
              <span className="text-quiet"> · {(universe.venues as string[]).join(", ")}</span>
            )}
          </div>
        ) : null}
        {features.length > 0 && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-quiet">Signals </span>
            {features.map((f) => (
              <Badge key={f} variant="iris" className="text-[10px]">{f}</Badge>
            ))}
          </div>
        )}
        {paramKeys.length > 0 && (
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-quiet">
              Params{Object.keys(params).length > 0 ? " (fitted)" : ""}{" "}
            </span>
            <span className="font-mono text-[11px] text-muted">
              {paramKeys.slice(0, 5).map((k) => `${k}=${typeof fitted[k] === "number" ? (fitted[k] as number).toPrecision(3) : fitted[k]}`).join(", ")}
              {paramKeys.length > 5 && ` +${paramKeys.length - 5} more`}
            </span>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => router.push(`/strategy/${versionId}`)}
        className="text-[11px] font-medium text-iris-soft hover:underline"
      >
        Full detail →
      </button>
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
