// Full costs ledger — LLM calls, infra lines, and per-strategy ROI.
// Linked from the Costs page DataPreview "View all" button.
// Server-fetches all cost data; client-side sort + filter via DataTablePage.

import { ArrowLeft, Bot, Cpu, TrendingDown, TrendingUp, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { getCosts, engineConfigured } from "../../data";
import { getSupplierCosts } from "../../data/supplier-costs";
import type { InfraLine, CostPerStrategy } from "../../data";
import type { SupplierRow } from "../../data/supplier-costs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { InfraTable } from "./infra-table";
import { SupplierTable } from "./supplier-table";
import { formatUsd, formatSigned, timeAgo } from "@/lib/utils";

export default async function CostsLedgerPage() {
  const [supplierResult, engineResult] = await Promise.all([
    getSupplierCosts(),
    getCosts()
  ]);

  const { costs, connected } = engineResult;
  const { rows: supplierRows, total_usd: supplierTotal, computed_at } = supplierResult;

  return (
    <div className="mx-auto max-w-[1200px] space-y-8 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div className="flex items-start gap-3">
        <Link
          href="/costs"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Costs
        </Link>
        <SectionHeader
          eyebrow="costs · ledger"
          title="Full cost ledger"
          className="flex-1"
        />
      </div>

      {/* Supplier breakdown */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[13px] font-semibold text-foreground">Monthly supplier spend</h2>
          {timeAgo(computed_at) && (
            <span className="text-[11px] text-quiet">refreshed {timeAgo(computed_at)} ago · 30 min cache</span>
          )}
        </div>
        <Card>
          <CardContent className="pt-5">
            <SupplierTable rows={supplierRows} total={supplierTotal} />
          </CardContent>
        </Card>
      </section>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="LLM call ledger, engine infra lines, and per-strategy ROI require the engine. Supplier costs above are fetched directly."
        />
      ) : (
        <>
          {/* LLM call ledger */}
          <section className="space-y-3">
            <h2 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
              <Bot className="size-4 text-iris-soft" /> LLM call ledger
            </h2>
            <Card>
              <CardContent className="py-4">
                {costs.llm_calls.call_count === 0 ? (
                  <EmptyState
                    title="No LLM calls recorded yet."
                    hint="Every call through the LLM gateway is recorded here once the engine has run at least one autonomous tick."
                    icon={<Bot className="size-5" />}
                  />
                ) : (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
                      <div>
                        <span className="text-quiet">Total calls</span>{" "}
                        <span className="font-semibold text-foreground tabular">
                          {costs.llm_calls.call_count.toLocaleString()}
                        </span>
                      </div>
                      <div>
                        <span className="text-quiet">Total cost</span>{" "}
                        <span className="font-semibold text-up tabular">
                          {costs.llm_calls.total_cost === 0
                            ? "$0 (:free tier)"
                            : formatUsd(costs.llm_calls.total_cost, 4)}
                        </span>
                      </div>
                    </div>
                    {Object.entries(costs.llm_calls.by_task).length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(costs.llm_calls.by_task).map(([task, count]) => (
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
                )}
              </CardContent>
            </Card>
          </section>

          {/* Engine infra lines */}
          {costs.infra_lines.length > 0 && (
            <section className="space-y-3">
              <h2 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
                <Cpu className="size-4 text-iris-soft" /> Engine infra lines
              </h2>
              <Card>
                <CardContent className="pt-5">
                  <InfraTable rows={costs.infra_lines} />
                </CardContent>
              </Card>
            </section>
          )}

          {/* Per-strategy ROI */}
          <section className="space-y-3">
            <h2 className="text-[13px] font-semibold text-foreground">Per-strategy ROI</h2>
            {costs.per_strategy.length === 0 ? (
              <Card>
                <CardContent>
                  <EmptyState
                    title="No strategy-attributed costs yet."
                    hint="Once LLM calls are attributed to a strategy version, ROI (opex vs net P&L) appears here."
                  />
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {costs.per_strategy.map((row: CostPerStrategy) => (
                  <RoiCard key={row.version_id} row={row} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function RoiCard({ row }: { row: CostPerStrategy }) {
  const profitable = row.net >= 0;
  const roi = row.opex > 0 ? row.net / row.opex : null;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[13.5px] font-medium text-foreground">{row.name}</div>
            <div className="truncate text-[11px] text-quiet">{row.version_id.slice(0, 8)}</div>
          </div>
          <Badge variant={profitable ? "up" : "down"}>
            {profitable ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
            {profitable ? "profitable" : "underwater"}
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <MetricCell label="Opex" value={formatUsd(row.opex, 2)} tone="text-muted" />
          <MetricCell
            label="Net P&L"
            value={formatSigned(row.net)}
            tone={profitable ? "text-up" : "text-down"}
          />
          <MetricCell
            label="ROI"
            value={roi !== null ? `${(roi * 100).toFixed(0)}%` : "—"}
            tone={roi === null ? "text-quiet" : roi >= 1 ? "text-up" : roi >= 0 ? "text-warn" : "text-down"}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function MetricCell({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-2">
      <div className={`text-[14px] font-semibold tabular ${tone}`}>{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
