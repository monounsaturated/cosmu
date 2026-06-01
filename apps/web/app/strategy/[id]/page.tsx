import { engineConfigured, getStrategy } from "../../data";
import type { Backtest, Execution, Point } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EquityCurve } from "@/components/charts/equity-curve";
import { FoldBars } from "@/components/charts/fold-bars";
import { ChartEmpty } from "@/components/charts/chart-kit";
import { NotConnected } from "@/components/ui/honest-state";

// Derive a paper equity curve from the strategy's trade log: cumulative realized cash flow
// (sells add, buys subtract, fees always subtract), seeded at 0. Honest — built only from the
// real trades the engine returned; no fabricated track record.
function paperCurveFromTrades(trades: Execution[]): Point[] {
  if (trades.length < 2) return [];
  let acc = 0;
  return trades.map((t) => {
    const gross = t.side === "sell" ? t.qty * t.price : -t.qty * t.price;
    acc += gross - t.fee;
    return { ts: t.ts, value: acc };
  });
}

export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { strategy, connected } = await getStrategy(id);
  const paperCurve = paperCurveFromTrades(strategy.trades);

  if (!connected || !strategy.version_id) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">version</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">{id}</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="This Version's evidence — Sleeve %, lineage, why it died, and charts — comes from the live engine. Nothing is fabricated."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">{strategy.name}</h1>
        <div className="mt-1.5 flex items-center gap-2 font-mono text-[12px] text-quiet">
          <span>{strategy.version_id}</span>
          <span className="text-border-strong">·</span>
          <span className="font-sans text-muted">deterministic evidence</span>
        </div>
      </div>

      {/* Evidence visuals: paper equity from trades + per-fold OOS returns */}
      <div className="grid gap-3 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Paper equity
              <Tooltip content="Cumulative realized cash flow from this sleeve's paper trades (sells add, buys and fees subtract). Built only from real trades — not a fabricated curve." />
            </CardTitle>
            <Badge variant="info">PAPER</Badge>
          </CardHeader>
          <CardContent>
            {paperCurve.length >= 2 ? (
              <EquityCurve points={paperCurve} mode="paper" height={220} valueLabel="Realized P&L" />
            ) : (
              <ChartEmpty title="Not enough trades yet" hint="A paper equity curve renders once this sleeve has at least two fills." height={220} />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Out-of-sample by fold
              <Tooltip content="Net return on each backtest fold (WFO, untouched holdout). Green is positive OOS return, red negative." />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <FoldBars backtests={strategy.backtests} height={220} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Spec</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <pre className="overflow-x-auto rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] leading-relaxed text-iris-soft">
              {JSON.stringify(strategy.spec, null, 2)}
            </pre>
            <div>
              <CardTitle className="mb-2">Trades</CardTitle>
              <Table>
                <THead>
                  <TR>
                    <TH>Side</TH>
                    <TH className="text-right">Qty</TH>
                    <TH className="text-right">Price</TH>
                    <TH className="text-right">Fee</TH>
                    <TH>Venue</TH>
                  </TR>
                </THead>
                <TBody>
                  {strategy.trades.map((trade: Execution) => (
                    <TR key={trade.id}>
                      <TD>
                        <Badge variant={trade.side === "buy" ? "up" : "down"}>{trade.side}</Badge>
                      </TD>
                      <TD className="text-right tabular text-foreground">{trade.qty}</TD>
                      <TD className="text-right tabular text-foreground">{trade.price}</TD>
                      <TD className="text-right tabular text-muted">{trade.fee}</TD>
                      <TD className="text-quiet">{trade.venue}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Gate history</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {strategy.backtests.map((bt: Backtest) => (
              <div key={bt.id} className="rounded-md border border-border/60 bg-surface-2/40 p-3.5">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium uppercase tracking-wide text-foreground">{bt.kind}</span>
                  <Badge variant={bt.passed_gates ? "up" : "down"}>{bt.passed_gates ? "passed" : "blocked"}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-[12.5px]">
                  <div className="flex items-center justify-between">
                    <span className="text-muted">deflated Sharpe</span>
                    <span className="tabular text-foreground">{bt.deflated_sharpe.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted">PBO</span>
                    <span className="tabular text-foreground">{bt.pbo.toFixed(2)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted">OOS return</span>
                    <span className="tabular text-up">{(bt.oos_return * 100).toFixed(1)}%</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted">win rate</span>
                    <span className="tabular text-foreground">{(bt.win_rate * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>
            ))}
            <div>
              <CardTitle className="mb-2">Compiled code</CardTitle>
              <pre className="overflow-x-auto rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] leading-relaxed text-iris-soft">
                {strategy.generated_code}
              </pre>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
