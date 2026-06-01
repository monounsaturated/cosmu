import { ArrowLeft, ScrollText } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getStrategy } from "../../data";
import type { Backtest, Execution, Point } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EquityCurve } from "@/components/charts/equity-curve";
import { FoldBars } from "@/components/charts/fold-bars";
import { ChartEmpty } from "@/components/charts/chart-kit";
import { SpecView } from "@/components/strategy/spec-view";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { cn, formatUsd } from "@/lib/utils";

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

// Render a free-form holdout record (e.g. {passed, deflated_sharpe, seen_once}) as labelled rows.
// The contract types holdout as Record<string, unknown>; format known number/bool shapes nicely.
function holdoutRows(holdout: Record<string, unknown>): { label: string; value: string; tone?: "up" | "down" }[] {
  return Object.entries(holdout).map(([k, v]) => {
    const label = k.replace(/_/g, " ");
    if (typeof v === "boolean") return { label, value: v ? "yes" : "no", tone: v ? "up" : "down" };
    if (typeof v === "number") return { label, value: v.toFixed(2) };
    return { label, value: String(v) };
  });
}

// Strategy detail is the DEFINITIVE inspect view for one Version: the spec (named features, params,
// composable modules), the compiled code, the full trade blotter, the OOS/holdout + per-fold
// evidence, and the agent post-mortem/notes. All from the existing strategy detail endpoint —
// nothing fabricated; honest empty states throughout.
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
          what="This Version's full picture — spec, compiled code, trade blotter, OOS/holdout evidence, and the agent post-mortem — comes from the live engine. Nothing is fabricated."
        />
      </div>
    );
  }

  const holdout = holdoutRows(strategy.holdout as Record<string, unknown>);

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
      <div>
        <Link href="/strategies" className="mb-2 inline-flex items-center gap-1 text-[12.5px] text-muted transition-colors hover:text-foreground">
          <ArrowLeft className="size-3.5" /> All Strategies
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">{strategy.name}</h1>
        <div className="mt-1.5 flex items-center gap-2 font-mono text-[12px] text-quiet">
          <span>{strategy.version_id}</span>
        </div>
      </div>

      {/* Evidence visuals: paper equity from trades + per-fold OOS returns + untouched holdout. */}
      <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
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
          <CardContent className="space-y-3">
            <FoldBars backtests={strategy.backtests} height={180} />
            {/* Untouched holdout — the one-shot, seen-once test that gates promotion. */}
            <div className="space-y-1.5 border-t border-border/50 pt-3">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-quiet">
                Untouched holdout
                <Tooltip content="The one-shot, seen-once test. A Version may only meet its holdout once — passing it is what allows promotion." />
              </div>
              {holdout.length ? (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px]">
                  {holdout.map((row) => (
                    <div key={row.label} className="flex items-center justify-between">
                      <dt className="text-muted">{row.label}</dt>
                      <dd className={cn("tabular", row.tone === "up" ? "text-up" : row.tone === "down" ? "text-down" : "text-foreground")}>
                        {row.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-[12px] text-quiet">No holdout recorded — this Version has not met its untouched holdout yet.</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* The spec — named features, composable modules, and fitted params. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Spec
            <Tooltip content="The typed hypothesis: universe, horizon, named features, composable entry/exit modules, risk rules, and the fitted param space. No magic numbers — thresholds are fit from data." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SpecView spec={strategy.spec} params={strategy.params} />
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        {/* Gate history — every backtest's deterministic verdict. */}
        <Card>
          <CardHeader>
            <CardTitle>Gate history</CardTitle>
            <Tooltip content="Each backtest's deterministic Gate verdict — deflated Sharpe, PBO, OOS return, win rate, and pass/block. The Gate decides promotion." />
          </CardHeader>
          <CardContent className="space-y-3">
            {strategy.backtests.length === 0 ? (
              <EmptyState title="No backtests yet." hint="Gate verdicts appear here once this Version has been backtested." />
            ) : (
              strategy.backtests.map((bt: Backtest) => (
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
                      <span className={cn("tabular", bt.oos_return >= 0 ? "text-up" : "text-down")}>{(bt.oos_return * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">win rate</span>
                      <span className="tabular text-foreground">{(bt.win_rate * 100).toFixed(0)}%</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">trades</span>
                      <span className="tabular text-foreground">{bt.num_trades}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">max DD</span>
                      <span className="tabular text-down">{(bt.max_dd * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Agent post-mortem / notes. */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <ScrollText className="size-4 text-iris-soft" /> Agent notes
              <Tooltip content="The authoring/post-mortem notes the agent recorded for this Version — why it was tried, and what was learned." />
            </CardTitle>
          </CardHeader>
          <CardContent>
            {strategy.notes_md ? (
              <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-muted">{strategy.notes_md}</div>
            ) : (
              <EmptyState title="No notes recorded." hint="The agent's rationale and post-mortem for this Version appear here when present." />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Trade blotter — the full fill log. */}
      <Card>
        <CardHeader>
          <CardTitle>Trade blotter</CardTitle>
          <Badge variant="muted">{strategy.trades.length} fills</Badge>
        </CardHeader>
        <CardContent>
          {strategy.trades.length === 0 ? (
            <EmptyState title="No trades yet." hint="Fills appear here as this sleeve trades on paper. Nothing is fabricated." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH className="sticky-col">Side</TH>
                  <TH className="text-right">Qty</TH>
                  <TH className="text-right">Price</TH>
                  <TH className="text-right">Fee</TH>
                  <TH>Venue</TH>
                  <TH>Time</TH>
                </TR>
              </THead>
              <TBody>
                {strategy.trades.map((trade: Execution) => (
                  <TR key={trade.id}>
                    <TD className="sticky-col">
                      <Badge variant={trade.side === "buy" ? "up" : "down"}>{trade.side}</Badge>
                    </TD>
                    <TD className="text-right tabular text-foreground">{trade.qty}</TD>
                    <TD className="text-right tabular text-foreground">{formatUsd(trade.price)}</TD>
                    <TD className="text-right tabular text-muted">{formatUsd(trade.fee)}</TD>
                    <TD className="text-quiet">{trade.venue ?? "—"}</TD>
                    <TD className="text-quiet">
                      <time dateTime={trade.ts}>{new Date(trade.ts).toLocaleString()}</time>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Compiled code — the deterministic artifact the spec compiled to. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Compiled code
            <Tooltip content="The deterministic code this Version's spec compiled to — what actually runs in the backtest and sleeve." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {strategy.generated_code ? (
            <pre className="max-h-[420px] overflow-auto rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] leading-relaxed text-iris-soft">
              {strategy.generated_code}
            </pre>
          ) : (
            <EmptyState title="No compiled code." hint="The compiled artifact appears here once this Version's spec has been compiled." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
