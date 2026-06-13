// Costs — the one question: is the machine's alpha worth more than what it costs to run?
//
// v18 shape (expense-tracker): the SAME interactive equity-style chart that fronts the dashboards
// (TvChart) sits on top, fed a CUMULATIVE-SPEND series. The CostsResponse contract carries no dated
// spend ledger today, so the hero renders TvChart's HONEST empty state (never a fabricated curve) and
// the verdict band + category / vendor / supplier / ROI / LLM sections carry the real figures beneath.
//
// Structure (chart on top, then verdict, then supporting context — progressive disclosure):
//   0. Cumulative-spend chart — TvChart hero (honest empty until the engine reports a dated spend series).
//   1. Verdict band — opex-vs-equity ratio as a trust read-out + total monthly opex + LLM spend.
//   2. Where the money goes — proportional category breakdown.
//   3. Vendor actuals — real actual-vs-budget per vendor (when the engine reports it).
//   4. Supplier spend — top suppliers (live vs estimated), full sortable ledger one click away.
//   5. Per-strategy ROI — opex vs net P&L at the strategy grain.
//   6. LLM calls — compact summary, full ledger one click away.
//
// HONESTY: NotConnected when the engine is unreachable (supplier billing still renders — it doesn't
// need the engine). Live supplier figures are marked "live"; estimates are marked "est." — nothing is
// fabricated. Empty / zero states say so plainly.

import type { Point } from "@cosmu/contracts-ts";
import { Bot } from "lucide-react";
import { engineConfigured, getCosts } from "../data";
import { getSupplierCosts } from "../data/supplier-costs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { DataPreview } from "@/components/ui/data-preview";
import { GaugeBar } from "@/components/ui/viz";
import { TvChart } from "@/components/charts/tv-chart";
import {
  CostSection,
  CategoryBreakdown,
  VendorActuals,
  SupplierPreviewTable,
  RoiCard,
  LlmCallsSummary,
  RefreshedAt,
} from "@/components/costs/cost-sections";
import { cn, formatUsd } from "@/lib/utils";

// The CostsResponse contract exposes no dated cumulative-spend series yet (only `total_usd`, a category
// split, vendor actuals, infra lines and an LLM summary — all point-in-time). When the engine starts
// reporting a dated spend ledger, surface it here as a Point[] and the hero chart lights up; until then
// the hero falls through to TvChart's honest empty. Never derive a curve from a single total — that
// would fabricate a trend.
function spendSeries(): Point[] {
  return [];
}

export default async function CostsPage() {
  const [supplierResult, engineResult] = await Promise.all([getSupplierCosts(), getCosts()]);
  const { costs, connected } = engineResult;
  const { rows: supplierRows, total_usd: supplierTotal, computed_at } = supplierResult;

  const liveCount = supplierRows.filter((r) => r.source === "live").length;
  const spend = spendSeries();

  return (
    <div className="mx-auto max-w-[1100px] space-y-7 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="costs"
        title="Opex vs alpha"
        aside={
          connected ? (
            <Badge variant="muted">{liveCount} live · {supplierRows.length - liveCount} estimated</Badge>
          ) : null
        }
      />

      {/* 0 · Cumulative-spend chart — the same interactive equity-style chart that fronts the dashboards,
          fed a cumulative-spend series. No dated series in the contract yet → TvChart's honest empty. */}
      <SpendChartHero points={spend} totalToDate={connected ? costs.total_usd : null} />

      {/* 1 · Verdict band — always rendered (supplier opex needs no engine). The opex-vs-equity ratio is
          the trust read-out; it only resolves when the engine reports equity, else an honest "—". */}
      <VerdictBand
        supplierTotal={supplierTotal}
        liveCount={liveCount}
        estCount={supplierRows.length - liveCount}
        opexVsEquity={connected ? costs.opex_vs_alpha : null}
        llmCalls={connected ? costs.llm_calls.call_count : null}
        llmCost={connected ? costs.llm_calls.total_cost : null}
      />

      {/* 2 · Where the money goes — only when the engine returned a real category split. */}
      {connected && costs.by_category.some((c) => c.amount > 0) ? (
        <CostSection
          title="Where the money goes"
          meaning="opex by category"
          aside={<span className="text-[11px] tabular text-quiet">{formatUsd(costs.total_usd)} total</span>}
        >
          <CategoryBreakdown categories={costs.by_category} />
        </CostSection>
      ) : null}

      {/* 3 · Vendor actuals — real billing actual-vs-budget per vendor, when the engine reports it. */}
      {connected && costs.vendor_actuals.length > 0 ? (
        <CostSection title="Vendor actuals" meaning="real spend vs budget, this period">
          <VendorActuals vendors={costs.vendor_actuals} />
        </CostSection>
      ) : null}

      {/* 4 · Supplier spend — top rows; full sortable ledger one click away. */}
      <CostSection title="Supplier spend" meaning="monthly" aside={<RefreshedAt at={computed_at} />}>
        <DataPreview href="/costs/ledger" viewAllLabel="Open full ledger" total={supplierRows.length}>
          <SupplierPreviewTable rows={supplierRows.slice(0, 5)} total={supplierTotal} />
        </DataPreview>
      </CostSection>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Per-strategy ROI and the LLM call ledger require the engine. Supplier spend above is fetched directly from each provider's billing API."
        />
      ) : (
        <>
          {/* 5 · Per-strategy ROI — opex vs net P&L at the strategy grain. */}
          {costs.per_strategy.length > 0 ? (
            <CostSection title="Per-strategy ROI" meaning="opex vs net P&L">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {costs.per_strategy.map((row) => (
                  <RoiCard key={row.version_id} name={row.name} versionId={row.version_id} opex={row.opex} net={row.net} />
                ))}
              </div>
            </CostSection>
          ) : null}

          {/* 6 · LLM calls — compact summary; full ledger one click away. */}
          <CostSection title="LLM calls" meaning="strategy authoring · proposals">
            <Card>
              <CardContent className="py-4">
                <DataPreview href="/costs/ledger" viewAllLabel="Open full ledger">
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
                </DataPreview>
              </CardContent>
            </Card>
          </CostSection>
        </>
      )}
    </div>
  );
}

// ─── Cumulative-spend chart hero ──────────────────────────────────────────────────
// The expense-tracker analogue of the dashboard equity hero: the SAME interactive TvChart (1M/3M/6M/All
// range selector, crosshair scrub, theme-reactive). Cumulative spend RISES, so it reads in the "live"
// money frame but is just a $ ledger — no P&L claim. With no dated series in the contract yet, TvChart
// shows its built-in honest empty (never a fabricated line); `totalToDate` is the one real figure we can
// state — the spend booked so far — so we surface it in the legend strip without inventing a curve.
function SpendChartHero({ points, totalToDate }: { points: Point[]; totalToDate: number | null }) {
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="mb-3 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-quiet">Cumulative spend</span>
          {totalToDate !== null ? (
            <span className="tabular text-[15px] font-semibold leading-none text-foreground">
              {formatUsd(totalToDate)}
            </span>
          ) : null}
          <span className="text-[11px] text-quiet">booked to date · every fee, fill &amp; vendor share</span>
        </div>
        <TvChart
          points={points}
          mode="live"
          height={260}
          valueKind="usd"
          emptyTitle="No dated spend ledger yet"
          emptyHint="The cumulative-spend curve renders once the engine reports a dated spend series. The verdict band and per-vendor figures below are real point-in-time totals — nothing here is fabricated."
        />
      </CardContent>
    </Card>
  );
}

// ─── Verdict band ───────────────────────────────────────────────────────────────
// The hero read-out. The opex-vs-equity ratio is the single trust number — total costs ÷ paper
// equity — toned green (≤2%) / gold (≤10%) / red (>10%). Monthly opex and LLM spend sit beside it as
// the two raw figures that feed it. Honest "—" for the ratio until the engine reports equity.
function VerdictBand({
  supplierTotal,
  liveCount,
  estCount,
  opexVsEquity,
  llmCalls,
  llmCost,
}: {
  supplierTotal: number;
  liveCount: number;
  estCount: number;
  opexVsEquity: number | null;
  llmCalls: number | null;
  llmCost: number | null;
}) {
  const ratioKnown = opexVsEquity !== null && opexVsEquity > 0;
  const ratioPct = ratioKnown ? (opexVsEquity as number) * 100 : null;
  const tone = ratioPct === null ? "muted" : ratioPct <= 2 ? "up" : ratioPct <= 10 ? "warn" : "down";
  const toneText: Record<string, string> = {
    up: "text-up",
    warn: "text-warn",
    down: "text-down",
    muted: "text-foreground",
  };
  const verdict =
    ratioPct === null
      ? "Needs equity to judge"
      : ratioPct <= 2
        ? "Opex is a rounding error vs alpha"
        : ratioPct <= 10
          ? "Opex is material — watch it"
          : "Opex is eating the alpha";

  return (
    <Card className="overflow-hidden">
      <CardContent className="grid gap-px p-0 sm:grid-cols-[1.4fr_1fr_1fr] sm:bg-border/40">
        {/* Primary — the ratio verdict */}
        <div className="bg-surface-2/20 p-5">
          <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">Opex vs equity</div>
          <div className={cn("mt-2 text-3xl font-semibold tracking-tight tabular", toneText[tone])}>
            {ratioPct === null ? "—" : `${ratioPct.toFixed(2)}%`}
          </div>
          <div className="mt-1 text-[12px] text-muted">{verdict}</div>
          {ratioPct !== null ? (
            <div className="mt-3">
              {/* Gauge to the 10% "material" line so the bar reads against a meaningful ceiling. */}
              <GaugeBar value={ratioPct} max={10} tone={tone === "muted" ? "iris" : tone} marker={0.2} />
              <div className="mt-1 flex justify-between text-[10px] tabular text-quiet">
                <span>0%</span>
                <span>2% target</span>
                <span>10%</span>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-[11px] leading-relaxed text-quiet">
              total costs ÷ paper equity — resolves once the engine reports equity.
            </p>
          )}
        </div>

        {/* Monthly opex */}
        <div className="bg-surface-2/20 p-5">
          <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">Monthly opex</div>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular text-foreground">
            {formatUsd(supplierTotal)}
          </div>
          <div className="mt-1 text-[12px] text-muted">
            {liveCount} live · {estCount} estimated
          </div>
        </div>

        {/* LLM spend */}
        <div className="bg-surface-2/20 p-5">
          <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">LLM spend</div>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular text-foreground">
            {llmCost === null ? "—" : llmCost === 0 ? "$0" : formatUsd(llmCost, 2)}
          </div>
          <div className="mt-1 text-[12px] text-muted">
            {llmCalls === null
              ? "engine not connected"
              : llmCalls === 0
                ? "no calls yet"
                : `${llmCalls.toLocaleString()} calls · free tier`}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
