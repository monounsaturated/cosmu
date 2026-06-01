import { Coins, Gauge, Receipt, Scale } from "lucide-react";
import { engineConfigured, getCosts, getPortfolio } from "../data";
import type { CostSlice } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { Tooltip } from "@/components/ui/tooltip";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnected, NotConnectedBanner } from "@/components/ui/honest-state";
import { CostBars } from "@/components/charts/cost-bars";
import { CostAttribution } from "@/components/costs/cost-attribution";
import { formatUsd } from "@/lib/utils";

const OPEX_VS_ALPHA = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-foreground">Opex vs alpha</span> — running cost as a share of the trailing edge
      it produces. Lower is better; above ~50% the machine is spending more than it is earning.
    </p>
  </div>
);

// Costs answers ONE question: what does the machine cost, and is it worth it?
// Total opex, spend by category, the opex-vs-alpha ratio, and per-strategy cost-vs-net attribution.
// Sourced from GET /costs, with /portfolio as a cross-check for the headline ratio. All real —
// honest empty states, never fabricated numbers.
export default async function CostsPage() {
  const [{ costs, connected }, { portfolio, connected: pConnected }] = await Promise.all([getCosts(), getPortfolio()]);

  const anyConnected = connected || pConnected;

  if (!anyConnected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
        <SectionHeader eyebrow="costs" title="What does the machine cost?" />
        <NotConnected
          configured={engineConfigured}
          what="Costs shows opex vs the alpha it buys — total spend, breakdown by category (LLM, data, sandbox, infra), and per-strategy cost-vs-net attribution. All real, never fabricated."
        />
      </div>
    );
  }

  // Prefer the dedicated /costs payload; fall back to the portfolio's cost slices for the bar
  // breakdown when /costs hasn't shipped on this engine yet (both are the same snake_case shape).
  const byCategory: CostSlice[] = costs.by_category.length ? costs.by_category : portfolio.costs;
  const opexVsAlpha = connected ? costs.opex_vs_alpha : portfolio.opex_vs_alpha;
  const totalUsd = connected && costs.total_usd ? costs.total_usd : byCategory.reduce((sum, c) => sum + c.amount, 0);
  const hasCategories = byCategory.length > 0;
  const ratioPct = Math.round(opexVsAlpha * 100);

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="costs"
        title="What does the machine cost — and is it worth it?"
        aside={<Badge variant="muted">opex vs alpha · per-strategy ROI</Badge>}
      />

      {!anyConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Total opex"
          value={hasCategories ? formatUsd(totalUsd, 0) : "—"}
          accent="iris"
          icon={<Receipt className="size-4" />}
          hint={<span className="text-quiet">daily run cost</span>}
        />
        <Stat
          label="Opex vs alpha"
          value={hasCategories ? `${ratioPct}%` : "—"}
          accent={ratioPct <= 25 ? "up" : ratioPct <= 50 ? "warn" : "down"}
          icon={<Gauge className="size-4" />}
          hint={<span className="inline-flex items-center gap-1 text-quiet">share of edge <Tooltip content={OPEX_VS_ALPHA} /></span>}
        />
        <Stat
          label="Categories"
          value={hasCategories ? byCategory.length : "—"}
          accent="iris"
          icon={<Coins className="size-4" />}
        />
        <Stat
          label="Funded Versions"
          value={connected && costs.per_strategy.length ? costs.per_strategy.length : "—"}
          accent="up"
          icon={<Scale className="size-4" />}
        />
      </section>

      {/* Spend by category + opex-vs-alpha gauge */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <Receipt className="size-4 text-iris-soft" /> Spend by category
            </CardTitle>
            <Tooltip content="What the machine spends on each day — LLM calls, market data, the strategy sandbox, and infra — and how big that is vs the trailing edge it produces." />
          </CardHeader>
          <CardContent>
            {hasCategories ? (
              <CostBars costs={byCategory} opexVsAlpha={opexVsAlpha} />
            ) : (
              <EmptyState
                title="No cost data yet."
                hint="Opex appears here once the engine starts spending on research (model, data, sandbox, infra)."
              />
            )}
          </CardContent>
        </Card>
      </section>

      {/* Per-strategy cost-vs-net attribution */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <Scale className="size-4 text-iris-soft" /> Cost vs net by Version
            </CardTitle>
            <Tooltip content="For each funded Version: opex spent vs net P&L earned, and the resulting ROI multiple (net ÷ opex). Click a row to inspect the Version." />
          </CardHeader>
          <CardContent>
            <CostAttribution rows={connected ? costs.per_strategy : []} />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
