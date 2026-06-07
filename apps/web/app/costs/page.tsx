// Costs / Infra view
// Shows: (1) real supplier spend with per-supplier live/est breakdown,
//        (2) per-strategy ROI (opex vs net P&L), (3) LLM call ledger.
// Honest: NotConnected when engine is unreachable; EmptyState for empty tables.
// Supplier rows pull real billing APIs where a token is available; otherwise a
// clearly-labelled static estimate is shown — nothing is fabricated.

import { DollarSign, Cpu, Bot, Wifi, WifiOff } from "lucide-react";
import { engineConfigured, getCosts } from "../data";
import { getSupplierCosts } from "../data/supplier-costs";
import type { LlmCallSummary } from "../data";
import type { SupplierRow } from "../data/supplier-costs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { DataPreview } from "@/components/ui/data-preview";
import { formatUsd, timeAgo } from "@/lib/utils";

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

      {/* KPI strip */}
      <section className="grid grid-cols-3 gap-3">
        <Stat
          label="Monthly suppliers"
          value={formatUsd(supplierTotal)}
          hint={`${liveCount} live · ${supplierRows.length - liveCount} est`}
          accent="iris"
          icon={<Cpu className="size-4" />}
        />
        <Stat
          label="LLM calls recorded"
          value={costs.llm_calls.call_count.toLocaleString()}
          hint={costs.llm_calls.total_cost === 0 ? ":free tier — $0 spend" : formatUsd(costs.llm_calls.total_cost, 4)}
          accent="iris"
          icon={<Bot className="size-4" />}
        />
        <Stat
          label="Opex vs equity"
          value={costs.opex_vs_alpha === 0 ? "—" : `${(costs.opex_vs_alpha * 100).toFixed(2)}%`}
          hint="total costs ÷ sim equity"
          accent={costs.opex_vs_alpha <= 0.02 ? "up" : costs.opex_vs_alpha <= 0.1 ? "warn" : "down"}
          icon={<DollarSign className="size-4" />}
        />
      </section>

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
        <div className="flex flex-wrap gap-2">
          {tasks.map(([task, count]) => (
            <div
              key={task}
              className="flex items-center gap-1.5 rounded-md border border-border/60 bg-surface-2/30 px-2.5 py-1 text-[11.5px]"
            >
              <span className="text-quiet capitalize">{task}</span>
              <span className="font-medium text-foreground tabular">{Number(count)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


