import { Coins, Gauge, PieChart, Receipt, TrendingDown, TrendingUp } from "lucide-react";
import { engineConfigured, getLivePositions, getPortfolio } from "../data";
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
import { cn, formatPct, formatSigned, formatUsd } from "@/lib/utils";

const SLEEVE_VS_WALLET = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-foreground">Sleeve</span> — a Version&apos;s standardized $100k paper test, judged
      in net-of-fee %.
    </p>
    <p>
      <span className="font-semibold text-foreground">Wallet</span> — the single pooled paper account across funded
      Allocations.
    </p>
  </div>
);

// Paper answers ONE question: how is the Wallet doing?
// Pooled-Wallet equity, open positions, Allocations, costs, and P&L.
export default async function PaperPage() {
  const [{ portfolio, connected }, positions] = await Promise.all([getPortfolio(), getLivePositions()]);

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">paper</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">How is the Wallet doing?</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="Paper shows the single pooled Wallet — equity curve, open positions, Allocations, running costs, and net P&L. All real, never fabricated."
        />
      </div>
    );
  }

  const hasTrackRecord = portfolio.equity_curve.length >= 2;
  const equity = portfolio.equity_curve.at(-1)?.value ?? 0;
  const start = portfolio.equity_curve[0]?.value ?? 0;
  const returnPct = hasTrackRecord && start ? ((equity - start) / start) * 100 : 0;
  const costsTotal = portfolio.costs.reduce((sum: number, c: CostSlice) => sum + c.amount, 0);
  const up = returnPct >= 0;
  const mode = moneyMode({ live: portfolio.live_enabled });
  // Open paper positions come from the live snapshot while in paper mode (no real funds).
  const openPositions = positions.connected ? positions.positions : [];

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:space-y-7 lg:px-7">
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
      </section>

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
        <Stat label="Opex vs alpha" value={portfolio.costs.length ? `${Math.round(portfolio.opex_vs_alpha * 100)}%` : "—"} accent="warn" icon={<Gauge className="size-4" />} />
        <Stat label="Daily opex" value={portfolio.costs.length ? formatUsd(costsTotal, 0) : "—"} accent="iris" />
      </section>

      {/* Wallet equity */}
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

      {/* Allocations + costs */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <CardTitle className="flex items-center gap-1.5">
                <PieChart className="size-4 text-iris-soft" /> Allocations
              </CardTitle>
              <Tooltip content="Each funded Version's Allocation — its share of the pooled Wallet, by weight and capital." />
            </div>
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
            <Tooltip content="What it costs to run the machine each day (LLM, data, sandbox, infra) and how big that is vs the trailing edge." />
          </CardHeader>
          <CardContent>
            {portfolio.costs.length ? (
              <CostBars costs={portfolio.costs} opexVsAlpha={portfolio.opex_vs_alpha} />
            ) : (
              <EmptyState title="No cost data yet." hint="Opex appears once the engine starts spending on research." />
            )}
          </CardContent>
        </Card>
      </section>

      {/* Open positions */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle>Open positions</CardTitle>
            <Badge variant="muted">{openPositions.length} open</Badge>
          </CardHeader>
          <CardContent>
            {openPositions.length === 0 ? (
              <EmptyState
                title="No open positions."
                hint="Positions appear here as the Wallet trades on paper within its caps. Nothing is fabricated."
              />
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
