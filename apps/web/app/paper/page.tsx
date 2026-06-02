import { ArrowRight, Coins, Gauge, PieChart, Radio, Receipt, Scale, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getCosts, getLivePositions, getPortfolio } from "../data";
import type { Allocation, CostSlice } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { Tooltip } from "@/components/ui/tooltip";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { EquityCurve } from "@/components/charts/equity-curve";
import { AllocationChart } from "@/components/charts/allocation-chart";
import { CostBars } from "@/components/charts/cost-bars";
import { CostAttribution } from "@/components/costs/cost-attribution";
import { SLEEVE_VS_WALLET } from "@/lib/shared-content";
import { cn, formatPct, formatSigned, formatUsd } from "@/lib/utils";

export default async function PaperPage() {
  const [{ portfolio, connected }, positions, { costs, connected: costsConnected }] = await Promise.all([
    getPortfolio(),
    getLivePositions(),
    getCosts()
  ]);

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">paper</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">How is the Wallet doing?</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="Paper shows the single pooled Wallet — equity curve, open positions, allocations, costs, and net P&L. All real, never fabricated."
        />
      </div>
    );
  }

  const hasTrackRecord = portfolio.equity_curve.length >= 2;
  const equity = portfolio.equity_curve.at(-1)?.value ?? 0;
  const start = portfolio.equity_curve[0]?.value ?? 0;
  const returnPct = hasTrackRecord && start ? ((equity - start) / start) * 100 : 0;
  const up = returnPct >= 0;
  const mode = moneyMode({ live: portfolio.live_enabled });
  const openPositions = positions.connected ? positions.positions : [];

  const byCategory: CostSlice[] = costsConnected && costs.by_category.length ? costs.by_category : portfolio.costs;
  const opexVsAlpha = costsConnected ? costs.opex_vs_alpha : portfolio.opex_vs_alpha;
  const totalOpex = byCategory.reduce((sum, c) => sum + c.amount, 0);
  const hasOpex = byCategory.length > 0;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      {/* Headline */}
      <section className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">Wallet · net return</span>
            <MoneyState mode={mode} />
          </div>
          {hasTrackRecord ? (
            <div className={`mt-1.5 text-[2.5rem] font-semibold leading-none tracking-tight tabular sm:text-5xl ${up ? "text-up" : "text-down"}`}>
              {formatPct(returnPct)}
            </div>
          ) : (
            <div className="mt-1.5 text-[2.5rem] font-semibold leading-none tracking-tight tabular text-quiet sm:text-5xl">—</div>
          )}
        </div>
        {/* The next step in the lifecycle: a forward-tested sleeve graduates to real money on Live. */}
        <Link
          href="/live"
          className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-surface-2/40 px-3 py-2 text-[12.5px] font-medium text-foreground transition-colors hover:border-info/60 hover:bg-info/10 hover:text-info"
        >
          <Radio className="size-3.5 text-info" /> Promote to Live <ArrowRight className="size-3.5" />
        </Link>
      </section>

      {/* KPIs */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Wallet equity"
          value={hasTrackRecord ? formatUsd(equity) : "—"}
          accent="iris"
          icon={<Coins className="size-4" />}
          hint={<span className="inline-flex items-center gap-1 text-quiet">pooled paper <Tooltip content={SLEEVE_VS_WALLET} /></span>}
        />
        <Stat
          label="Net P&L"
          value={hasTrackRecord ? <span className={up ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span> : "—"}
          accent={up ? "up" : "down"}
          icon={up ? <TrendingUp className="size-4" /> : <TrendingDown className="size-4" />}
        />
        <Stat
          label="Opex vs alpha"
          value={hasOpex ? `${Math.round(opexVsAlpha * 100)}%` : "—"}
          accent={!hasOpex ? "iris" : opexVsAlpha <= 0.25 ? "up" : opexVsAlpha <= 0.5 ? "warn" : "down"}
          icon={<Gauge className="size-4" />}
          hint={<span className="text-quiet">cost as % of edge</span>}
        />
        <Stat label="Open positions" value={openPositions.length} accent="iris" />
      </section>

      {/* Equity curve */}
      <section>
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <CardTitle>Wallet equity</CardTitle>
              <Tooltip content={SLEEVE_VS_WALLET} />
            </div>
            <MoneyState mode={mode} withInfo={false} />
          </CardHeader>
          <CardContent>
            <EquityCurve points={portfolio.equity_curve} mode={mode} height={260} />
          </CardContent>
        </Card>
      </section>

      {/* Allocations + running costs */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <PieChart className="size-4 text-iris-soft" /> Allocations
            </CardTitle>
            <Tooltip content="Each funded Version's share of the pooled Wallet, by weight and capital." />
          </CardHeader>
          <CardContent>
            <AllocationChart allocation={portfolio.allocation as Allocation[]} height={220} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <Receipt className="size-4 text-iris-soft" /> Running costs
            </CardTitle>
            <Tooltip content="Daily spend by category (LLM, data, sandbox, infra) and how it compares to the edge produced." />
          </CardHeader>
          <CardContent>
            {hasOpex ? (
              <CostBars costs={byCategory} opexVsAlpha={opexVsAlpha} />
            ) : (
              <EmptyState title="No cost data yet." hint="Opex appears once the engine starts spending on research." />
            )}
          </CardContent>
        </Card>
      </section>

      {/* Per-strategy cost attribution */}
      {costsConnected && costs.per_strategy.length > 0 && (
        <section>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <Scale className="size-4 text-iris-soft" /> Cost vs net by Version
              </CardTitle>
              <Tooltip content="For each funded Version: opex spent vs net earned, and the ROI multiple (net / opex)." />
            </CardHeader>
            <CardContent>
              <CostAttribution rows={costs.per_strategy} />
            </CardContent>
          </Card>
        </section>
      )}

      {/* Open positions */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle>Open positions</CardTitle>
            <Badge variant="muted">{openPositions.length} open</Badge>
          </CardHeader>
          <CardContent>
            {openPositions.length === 0 ? (
              <EmptyState title="No open positions." hint="Positions appear here as the Wallet trades on paper within its caps." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[12.5px]">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] uppercase tracking-wide text-quiet">
                      <th className="sticky-col px-2 py-2 font-medium">Symbol</th>
                      <th className="px-2 py-2 font-medium">Venue</th>
                      <th className="px-2 py-2 text-right font-medium">Qty</th>
                      <th className="px-2 py-2 text-right font-medium">Avg price</th>
                      <th className="px-2 py-2 text-right font-medium">Unrealized P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {openPositions.map((p) => (
                      <tr key={p.instrument_id} className="border-b border-border/40 last:border-0">
                        <td className="sticky-col px-2 py-2.5 font-medium text-foreground">{p.symbol}</td>
                        <td className="px-2 py-2.5 text-muted">{p.venue}</td>
                        <td className="px-2 py-2.5 text-right tabular text-muted">{p.qty}</td>
                        <td className="px-2 py-2.5 text-right tabular text-muted">{formatUsd(p.avg_price)}</td>
                        <td className={cn("px-2 py-2.5 text-right tabular", p.unrealized_pnl >= 0 ? "text-up" : "text-down")}>
                          {formatSigned(p.unrealized_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
