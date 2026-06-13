// Costs — Iris Bento port. The one question: is the machine's alpha worth more than what it costs to
// run? The mockup's `TXN`/`SUBS` arrays are SYNTHETIC and discarded entirely; we keep only the bento DOM
// (stat-strip · spend chart · category tiles · register table) and bind the REAL CostsResponse +
// supplier billing.
//
// Layout (top → bottom):
//   0. stat-strip — lifetime/total spend, run-rate, vs-equity (honest "—" when a figure has no source).
//   1. spend chart card — honest EQUITY-style empty (no dated spend series exists in the contract).
//   2. category tiles — real CostsResponse.by_category.
//   3. register card — every cost source (supplier billing + infra lines + vendor actuals).
//   4. LLM calls — compact summary (engine-only).
//
// HONESTY: live money is never conflated with sim. The engine sections show <NotConnected/> when the
// engine is unreachable; supplier billing renders regardless (it's fetched directly). vs-equity stays
// "—" until `opex_vs_alpha` is real. No fabricated spend curve, no synthetic ledger.

import { Suspense } from "react";
import { engineConfigured, getCosts } from "../data";
import { getSupplierCosts } from "../data/supplier-costs";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import {
  CardHead,
  CategoryTiles,
  LlmCallsSummary,
  RefreshedAt,
  RegisterTable,
  RoiTable,
  SpendChartCard,
  StatStrip,
  buildRegister,
  type StatCell,
} from "@/components/costs/cost-sections";
import { formatUsd } from "@/lib/utils";

// On-demand: the engine may be offline at build time, and supplier billing is fetched live. Never
// statically pre-render — the honest not-connected/empty states must reflect the real moment.
export const dynamic = "force-dynamic";

export default function CostsPage() {
  return (
    <Page>
      <Toolbar title="Costs" />
      <Suspense fallback={<div className="skel" style={{ height: 420 }} />}>
        <CostsData />
      </Suspense>
    </Page>
  );
}

async function CostsData() {
  const [supplierResult, engineResult] = await Promise.all([getSupplierCosts(), getCosts()]);
  const { costs, connected } = engineResult;
  const { rows: supplierRows, total_usd: supplierTotal, computed_at } = supplierResult;

  // Run-rate: the monthly supplier billing total — the realest forward figure we have.
  const runRate = supplierTotal;
  // vs-equity: only real when the engine reports `opex_vs_alpha` (a fraction). Honest "—" otherwise.
  const vsEquity = connected && costs.opex_vs_alpha > 0 ? costs.opex_vs_alpha * 100 : null;
  // Lifetime/total spend: the engine's `total_usd` when connected; else honest "—" (we don't sum a
  // synthetic ledger). Supplier total is monthly, not lifetime, so it is NOT used here.
  const totalSpend = connected ? costs.total_usd : null;

  const liveCount = supplierRows.filter((r) => r.source === "live").length;
  const estCount = supplierRows.length - liveCount;

  const cells: StatCell[] = [
    {
      label: "Total spend",
      value: totalSpend === null ? "—" : formatUsd(totalSpend),
      sub: totalSpend === null ? "engine not connected" : "booked to date",
    },
    {
      label: "Run-rate",
      value: formatUsd(runRate),
      sub: `${liveCount} live · ${estCount} est. · /mo`,
    },
    {
      label: "vs equity",
      value: vsEquity === null ? "—" : `${vsEquity.toFixed(1)}%`,
      sub: vsEquity === null ? "needs equity" : "opex / equity",
      tone: vsEquity !== null && vsEquity <= 2 ? "up" : vsEquity !== null && vsEquity > 10 ? "dn" : undefined,
    },
    {
      label: "LLM spend",
      value: !connected ? "—" : costs.llm_calls.total_cost === 0 ? "$0" : formatUsd(costs.llm_calls.total_cost, 2),
      sub: !connected
        ? "engine not connected"
        : costs.llm_calls.call_count === 0
          ? "no calls yet"
          : `${costs.llm_calls.call_count.toLocaleString()} calls · free tier`,
    },
  ];

  const register = buildRegister(supplierRows, connected ? costs.infra_lines : [], connected ? costs.vendor_actuals : []);
  const hasCategories = connected && costs.by_category.some((c) => c.amount > 0);

  return (
    <>
      {!connected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* 0 · stat strip — real totals, honest "—" where a source is missing. */}
      <StatStrip cells={cells} />

      {/* 1 · spend chart — honest empty (no dated series in the contract). */}
      <SpendChartCard totalToDate={totalSpend} />

      {/* 2 · category tiles — only when the engine returned a real split. */}
      {hasCategories ? <CategoryTiles categories={costs.by_category} /> : null}

      {/* 3 · register — every cost source the contract gives us (supplier + infra + actuals). */}
      <div className="card" style={{ marginBottom: "var(--gap)" }}>
        <CardHead label={`Cost register · ${register.length} source${register.length === 1 ? "" : "s"}`} aside={<RefreshedAt at={computed_at} />} />
        <div className="card-body">
          <RegisterTable rows={register} />
          <div className="costs-note">
            Live figures are fetched from each provider&apos;s billing API; <code>actual</code> rows are
            engine-reported real spend vs budget; the rest are clearly-labelled plan-tier estimates. Headroom
            is shown only where a real budget cap exists. Nothing here is fabricated.
          </div>
        </div>
      </div>

      {/* 4 · per-strategy ROI — the literal opex-vs-alpha question at the strategy grain (engine-only,
          only when the engine attributed opex to a strategy). Net P&L here is the engine-attributed
          per-strategy net — never conflated with the live wallet. */}
      {connected && costs.per_strategy.length > 0 ? (
        <div className="card" style={{ marginBottom: "var(--gap)" }}>
          <CardHead label="Per-strategy ROI" aside="opex vs net P&L" />
          <div className="card-body">
            <RoiTable rows={costs.per_strategy} />
          </div>
        </div>
      ) : null}

      {/* 5 · LLM calls — engine-only; honest "—"/empty when unavailable. */}
      <div className="card">
        <CardHead label="LLM calls" aside={connected ? "strategy authoring" : null} />
        <div className="card-body">
          {connected ? (
            <LlmCallsSummary
              callCount={costs.llm_calls.call_count}
              totalCost={costs.llm_calls.total_cost}
              byTask={costs.llm_calls.by_task}
            />
          ) : (
            <div className="quiet" style={{ fontSize: 12, padding: "6px 0" }}>
              The LLM call ledger requires the engine. Supplier billing above is fetched directly.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
