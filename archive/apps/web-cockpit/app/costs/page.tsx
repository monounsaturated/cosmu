// Costs — the one question: is the machine's alpha worth more than what it costs to run? The page binds
// the code-maintained cost register (apps/web/app/data/cost-register.ts — the source of truth, reconciled
// against the provider invoices) plus the engine's per-strategy ROI / spend series.
//
// Layout (top → bottom):
//   0. spend chart card — total spent to date (+ engine spend_series when it exists).
//   1. boards (CostsRegister) — stat strip (total · run-rate · vs-equity · Other) + the four category
//      tiles + the read-only subscriptions register; one shared click-to-filter state.
//   2. per-strategy ROI — engine-only opex-vs-alpha at the strategy grain.
//
// HONESTY: the register is real, operator-known spend (no fabricated curve, no live billing guesswork).
// Engine sections show <NotConnected/> when the engine is unreachable; vs-equity stays "—" until
// `opex_vs_alpha` is real.

import { Suspense } from "react";
import { engineConfigured, getCosts } from "../data";
import { buildCostLines, costTotals } from "../data/cost-register";
import { getEurUsd } from "../data/fx";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import { CardHead, RoiTable, SpendChartCard } from "@/components/costs/cost-sections";
import { CostsRegister } from "@/components/costs/costs-register";

// On-demand: the engine may be offline at build time. Never statically pre-render — the honest
// not-connected/empty states must reflect the real moment.
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
  const [{ costs, connected }, eurUsd] = await Promise.all([getCosts(), getEurUsd()]);
  const lines = buildCostLines(eurUsd); // EUR spend re-rated with the live daily EUR→USD rate
  const { totalSpend } = costTotals(lines);

  // vs-equity: only real when the engine reports `opex_vs_alpha` (a fraction). Honest "—" otherwise.
  const vsEquity = connected && costs.opex_vs_alpha > 0 ? costs.opex_vs_alpha * 100 : null;

  return (
    <>
      {!connected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* 0 · spend chart — total spent to date (+ engine spend_series when present). */}
      <SpendChartCard totalToDate={totalSpend} spendSeries={connected ? costs.spend_series : null} />

      {/* 1 · boards — stat strip + clickable tiles + the read-only register they filter. */}
      <CostsRegister rows={lines} vsEquity={vsEquity} />

      {/* 2 · per-strategy ROI — opex-vs-alpha at the strategy grain (engine-only). */}
      {connected && costs.per_strategy.length > 0 ? (
        <div className="card" style={{ marginBottom: "var(--gap)" }}>
          <CardHead label="Per-strategy ROI" aside="opex vs net P&L" />
          <div className="card-body">
            <RoiTable rows={costs.per_strategy} />
          </div>
        </div>
      ) : null}
    </>
  );
}
