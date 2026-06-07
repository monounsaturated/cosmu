// Costs / Infra view
// Shows: (1) real supplier spend with per-supplier live/est breakdown,
//        (2) per-strategy ROI (opex vs net P&L), (3) LLM call ledger.
// Honest: NotConnected when engine is unreachable; EmptyState for empty tables.
// Supplier rows pull real billing APIs where a token is available; otherwise a
// clearly-labelled static estimate is shown — nothing is fabricated.

import { DollarSign, Cpu, Bot, Wifi, WifiOff } from "lucide-react";
import { engineConfigured, getCosts } from "../data";
import { getSupplierCosts } from "../data/supplier-costs";
import type { CostsResponse, LlmCallSummary } from "@cosmu/contracts-ts";
import type { SupplierRow } from "../data/supplier-costs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { DataPreview } from "@/components/ui/data-preview";
import { MetricCard } from "@/components/ui/viz";
import { cn, formatUsd, timeAgo } from "@/lib/utils";

export default async function CostsPage() {
  // Fetch supplier costs (real + estimates) and engine costs in parallel.
  const [supplierResult, engineResult] = await Promise.all([
    getSupplierCosts(),
    getCosts(),
  ]);

  const { costs, connected } = engineResult;
  const { rows: supplierRows, total_usd: supplierTotal, computed_at } = supplierResult;

  if (!connected) {
    // Still show supplier costs — those don't need the engine.
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <SectionHeader eyebrow="costs · infra" title="What does running this cost?" />
        <section>
          <SupplierTable rows={supplierRows.slice(0, 4)} total={supplierTotal} computedAt={computed_at} fullCount={supplierRows.length} />
        </section>
        <NotConnected
          configured={engineConfigured}
          what="Per-strategy ROI and LLM call ledger require the engine. Supplier costs above are fetched directly."
        />
      </div>
    );
  }

  const liveCount = supplierRows.filter((r) => r.source === "live").length;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="costs · infra"
        title="What does running this cost?"
        aside={
          <Badge variant="iris">
            <DollarSign className="size-3" /> opex vs alpha
          </Badge>
        }
      />

      {/* KPI strip — dense metric tiles. Every number is real; no fabricated spend timeline (the engine
          exposes a current snapshot + a category breakdown, not a per-day series). */}
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <MetricCard
          label="Monthly suppliers"
          value={formatUsd(supplierTotal)}
          hint={`${liveCount} live · ${supplierRows.length - liveCount} est`}
          tone="iris"
          icon={<Cpu className="size-4" />}
        />
        <MetricCard
          label="LLM calls recorded"
          value={costs.llm_calls.call_count.toLocaleString()}
          hint={costs.llm_calls.total_cost === 0 ? ":free tier — $0 spend" : formatUsd(costs.llm_calls.total_cost, 4)}
          tone="iris"
          icon={<Bot className="size-4" />}
        />
        <MetricCard
          label="Opex vs equity"
          value={costs.opex_vs_alpha === 0 ? "—" : `${(costs.opex_vs_alpha * 100).toFixed(2)}%`}
          hint="total costs ÷ sim equity"
          tone={costs.opex_vs_alpha <= 0.02 ? "up" : costs.opex_vs_alpha <= 0.1 ? "warn" : "down"}
          icon={<DollarSign className="size-4" />}
        />
      </section>

      {/* Where the money goes — proportional category breakdown (real CostsResponse.by_category). */}
      <CostBreakdown costs={costs} />

      {/* Supplier breakdown preview — top 4 rows by cost. Full sortable ledger at /costs/ledger. */}
      <section>
        <SupplierTable rows={supplierRows.slice(0, 4)} total={supplierTotal} computedAt={computed_at} fullCount={supplierRows.length} />
      </section>

      {/* LLM call summary — compact, always visible. Full ledger at /costs/ledger. */}
      <section>
        <h2 className="mb-3 text-[13px] font-semibold text-foreground">LLM calls (summary)</h2>
        <Card>
          <CardContent className="py-4">
            <DataPreview href="/costs/ledger" viewAllLabel="View full ledger">
              <LlmCallsPanel summary={costs.llm_calls} />
            </DataPreview>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

// ─── Cost breakdown by category ─────────────────────────────────────────────────
// A compact horizontal breakdown of where opex goes, drawn from the REAL CostsResponse.by_category.
// Proportional bars read faster than a table; the $ figures stay the source of truth. Rendered only
// when the engine actually returned categories — never a fabricated split.
function CostBreakdown({ costs }: { costs: CostsResponse }) {
  const cats = [...costs.by_category].filter((c) => c.amount > 0).sort((a, b) => b.amount - a.amount);
  if (cats.length === 0) return null;
  const total = cats.reduce((s, c) => s + c.amount, 0) || 1;
  const tones = ["bg-iris", "bg-info/80", "bg-up/80", "bg-warn/80", "bg-iris-soft", "bg-down/70"];
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-semibold text-foreground">Where the money goes</h2>
        <span className="text-[11px] tabular text-quiet">{formatUsd(total)} total</span>
      </div>
      <Card>
        <CardContent className="space-y-2 py-4">
          {/* Single stacked proportion bar */}
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2">
            {cats.map((c, i) => (
              <div
                key={c.category}
                className={cn("h-full", tones[i % tones.length])}
                style={{ width: `${(c.amount / total) * 100}%` }}
                title={`${c.category}: ${formatUsd(c.amount)}`}
              />
            ))}
          </div>
          {/* Legend rows */}
          <ul className="mt-1 space-y-1.5">
            {cats.map((c, i) => (
              <li key={c.category} className="flex items-center gap-2.5 text-[12.5px]">
                <span className={cn("size-2.5 shrink-0 rounded-[3px]", tones[i % tones.length])} aria-hidden />
                <span className="flex-1 capitalize text-muted">{c.category}</span>
                <span className="tabular text-quiet">{((c.amount / total) * 100).toFixed(0)}%</span>
                <span className="w-16 text-right tabular font-medium text-foreground">{formatUsd(c.amount)}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

// ─── Supplier table ───────────────────────────────────────────────────────────

function SupplierTable({
  rows,
  total,
  computedAt,
  fullCount,
}: {
  rows: SupplierRow[];
  total: number;
  computedAt: string;
  fullCount: number;
}) {
  const ago = timeAgo(computedAt);
  return (
    <>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-[13px] font-semibold text-foreground">Monthly supplier spend</h2>
        {ago ? (
          <span className="text-[11px] text-quiet">refreshed {ago} ago · 30 min cache</span>
        ) : null}
      </div>
      <DataPreview href="/costs/ledger" viewAllLabel="View full ledger" total={fullCount}>
        <Card>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH className="pl-4 sticky-col">Supplier</TH>
                  <TH>Role</TH>
                  <TH className="text-right">$/mo</TH>
                  <TH>Source</TH>
                  <TH className="pr-4 text-right">Fetched</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <SupplierRow key={row.name} row={row} />
                ))}
                <TR className="bg-surface-2/30 font-semibold hover:bg-surface-2/30">
                  <TD className="pl-4 text-foreground sticky-col" colSpan={2}>
                    Total
                  </TD>
                  <TD className="text-right tabular text-foreground">{formatUsd(total)}</TD>
                  <TD className="pr-4 text-[11px] text-quiet" colSpan={2}>
                    mix of live + est — see source column
                  </TD>
                </TR>
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </DataPreview>
    </>
  );
}

function SupplierRow({ row }: { row: SupplierRow }) {
  const isLive = row.source === "live";
  const isFree = row.amount_usd === 0;
  const ago = timeAgo(row.fetched_at);
  return (
    <TR>
      <TD className="pl-4 font-medium text-foreground sticky-col">
        <div className="flex items-center gap-2">
          {row.name}
          <Badge variant={row.category === "llm" ? "iris" : row.category === "data" ? "info" : "muted"} className="text-[10px]">
            {row.category}
          </Badge>
        </div>
      </TD>
      <TD className="max-w-[260px] truncate text-quiet">{row.role}</TD>
      <TD className="text-right tabular text-foreground">
        {isFree ? <span className="text-[11px] text-up">free / $0</span> : formatUsd(row.amount_usd)}
      </TD>
      <TD>
        {isLive ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-up">
            <Wifi className="size-3" /> live
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted">
            <WifiOff className="size-3" /> est.
          </span>
        )}
      </TD>
      <TD className="pr-4 text-right text-[11px] tabular text-quiet">{ago ? `${ago} ago` : "—"}</TD>
    </TR>
  );
}

// ─── LLM calls panel ──────────────────────────────────────────────────────────

function LlmCallsPanel({ summary }: { summary: LlmCallSummary }) {
  const tasks = Object.entries(summary.by_task);
  if (summary.call_count === 0) {
    return (
      <EmptyState
        title="No LLM calls recorded yet."
        hint="Every call through the LLM gateway (strategy authoring, proposals) is recorded here once the engine has run at least one autonomous tick."
        icon={<Bot className="size-5" />}
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
        <div>
          <span className="text-quiet">Total calls</span>{" "}
          <span className="font-semibold text-foreground tabular">{summary.call_count.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-quiet">Total cost</span>{" "}
          <span className="font-semibold text-up tabular">
            {summary.total_cost === 0 ? "$0 (:free tier)" : formatUsd(summary.total_cost, 4)}
          </span>
        </div>
      </div>
      {tasks.length > 0 && (
        <div className="space-y-1.5 border-t border-border/40 pt-3">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">Calls by task</div>
          {(() => {
            const sorted = tasks.map(([task, count]) => ({ task, count: Number(count) })).sort((a, b) => b.count - a.count);
            const top = Math.max(1, ...sorted.map((t) => t.count));
            return sorted.map((t) => (
              <div key={t.task} className="flex items-center gap-2.5 text-[12px]">
                <span className="w-28 shrink-0 truncate capitalize text-muted">{t.task}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded bg-surface-2">
                  <div className="h-full rounded bg-iris/75" style={{ width: `${Math.max((t.count / top) * 100, 4)}%` }} />
                </div>
                <span className="w-8 shrink-0 text-right tabular font-medium text-foreground">{t.count}</span>
              </div>
            ));
          })()}
        </div>
      )}
    </div>
  );
}


