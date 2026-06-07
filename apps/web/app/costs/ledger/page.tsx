// Full cost ledger — the drill-down from the Costs page. Everything sortable / filterable:
// supplier spend, vendor actuals, the LLM call ledger, engine infra lines, and per-strategy ROI.
//
// HONESTY: NotConnected for the engine-backed sections when unreachable (supplier spend still renders
// — it's fetched directly). Live vs estimated is always labelled; empty / zero states say so.

import { ArrowLeft, Bot, Cpu } from "lucide-react";
import Link from "next/link";
import { getCosts, engineConfigured } from "../../data";
import { getSupplierCosts } from "../../data/supplier-costs";
import { Card, CardContent } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import {
  CostSection,
  VendorActuals,
  RoiCard,
  LlmCallsSummary,
  RefreshedAt,
} from "@/components/costs/cost-sections";
import { InfraTable } from "./infra-table";
import { SupplierTable } from "./supplier-table";

export default async function CostsLedgerPage() {
  const [supplierResult, engineResult] = await Promise.all([getSupplierCosts(), getCosts()]);
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
        <SectionHeader eyebrow="costs · ledger" title="Full cost ledger" className="flex-1" />
      </div>

      {/* Supplier spend — full sortable table (fetched directly; needs no engine). */}
      <CostSection title="Supplier spend" meaning="monthly" aside={<RefreshedAt at={computed_at} />}>
        <Card>
          <CardContent className="pt-5">
            <SupplierTable rows={supplierRows} total={supplierTotal} />
          </CardContent>
        </Card>
      </CostSection>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="The LLM call ledger, engine infra lines, vendor actuals, and per-strategy ROI require the engine. Supplier spend above is fetched directly from each provider's billing API."
        />
      ) : (
        <>
          {/* Vendor actuals — real spend vs budget. */}
          {costs.vendor_actuals.length > 0 ? (
            <CostSection title="Vendor actuals" meaning="real spend vs budget, this period">
              <VendorActuals vendors={costs.vendor_actuals} />
            </CostSection>
          ) : null}

          {/* LLM call ledger. */}
          <CostSection title="LLM call ledger" meaning="strategy authoring · proposals">
            <Card>
              <CardContent className="py-4">
                <LlmCallsSummary
                  callCount={costs.llm_calls.call_count}
                  totalCost={costs.llm_calls.total_cost}
                  byTask={costs.llm_calls.by_task}
                  empty={
                    <EmptyState
                      title="No LLM calls recorded yet."
                      hint="Every call through the LLM gateway is recorded here once the engine has run at least one autonomous tick."
                      icon={<Bot className="size-5" />}
                    />
                  }
                />
              </CardContent>
            </Card>
          </CostSection>

          {/* Engine infra lines — sortable. */}
          {costs.infra_lines.length > 0 ? (
            <CostSection title="Engine infra lines" meaning="estimated plan tiers">
              <Card>
                <CardContent className="pt-5">
                  <InfraTable rows={costs.infra_lines} />
                </CardContent>
              </Card>
            </CostSection>
          ) : null}

          {/* Per-strategy ROI. */}
          <CostSection title="Per-strategy ROI" meaning="opex vs net P&L">
            {costs.per_strategy.length === 0 ? (
              <Card>
                <CardContent>
                  <EmptyState
                    title="No strategy-attributed costs yet."
                    hint="Once LLM calls are attributed to a strategy version, ROI (opex vs net P&L) appears here."
                    icon={<Cpu className="size-5" />}
                  />
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {costs.per_strategy.map((row) => (
                  <RoiCard key={row.version_id} name={row.name} versionId={row.version_id} opex={row.opex} net={row.net} />
                ))}
              </div>
            )}
          </CostSection>
        </>
      )}
    </div>
  );
}
