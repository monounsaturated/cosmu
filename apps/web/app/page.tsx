import {
  ArrowUpRight,
  BrainCircuit,
  Coins,
  Gauge,
  Layers,
  Radio,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp
} from "lucide-react";
import Link from "next/link";
import { ConsoleBox } from "./console-box";
import { getEvents, getLeaderboard, getPortfolio, getRecommendations, getStrategy } from "./data";
import type { Allocation, Backtest, CostSlice, Event, LeaderboardRow, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { AreaChart } from "@/components/charts/area-chart";
import { formatPct, formatSigned, formatUsd } from "@/lib/utils";

const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  paper: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

export default async function HomePage() {
  const [portfolio, leaderboard, strategy, recommendations, events] = await Promise.all([
    getPortfolio(),
    getLeaderboard(),
    getStrategy("sv-btc"),
    getRecommendations(),
    getEvents()
  ]);

  const equity = portfolio.equity_curve.at(-1)?.value ?? 100000;
  const start = portfolio.equity_curve[0]?.value ?? 100000;
  const returnPct = ((equity - start) / start) * 100;
  const costsTotal = portfolio.costs.reduce((sum: number, c: CostSlice) => sum + c.amount, 0);
  const pnlUp = portfolio.pnl_net >= 0;

  return (
    <div className="mx-auto max-w-[1400px] space-y-10 px-5 py-7 lg:px-7">
      {/* Hero */}
      <section id="dashboard" className="space-y-6">
        <div className="relative overflow-hidden rounded-xl border border-border/70 card-grad p-6 lg:p-8">
          <div className="ring-grid pointer-events-none absolute inset-0 opacity-[0.35] [mask-image:radial-gradient(700px_280px_at_85%_0%,black,transparent)]" />
          <div className="relative max-w-3xl">
            <Badge variant="iris">
              <Sparkles className="size-3" />
              deterministic master · autonomous lab
            </Badge>
            <h1 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight text-foreground sm:text-4xl lg:text-[44px]">
              A self-learning money machine that <span className="text-iris-soft">refuses to fool itself.</span>
            </h1>
            <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-muted">
              A population of LLM-authored swing strategies, walk-forward backtested with real per-venue fees and farmed
              24/7 in realistic paper. The scorer and the money stay out of the agent&apos;s reach.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="Pooled paper equity"
            value={formatUsd(equity)}
            accent="iris"
            icon={<Coins className="size-4" />}
            hint={
              <span className="inline-flex items-center gap-1 text-up">
                <ArrowUpRight className="size-3.5" /> {formatPct(returnPct)} since inception
              </span>
            }
          />
          <Stat
            label="Net P&L (after costs)"
            value={<span className={pnlUp ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span>}
            accent={pnlUp ? "up" : "down"}
            icon={pnlUp ? <TrendingUp className="size-4" /> : <TrendingDown className="size-4" />}
            hint="money truth, net of every fee"
          />
          <Stat
            label="Opex vs alpha"
            value={`${Math.round(portfolio.opex_vs_alpha * 100)}%`}
            accent="warn"
            icon={<Gauge className="size-4" />}
            hint="auto-throttles below trailing edge"
          />
          <Stat
            label="Live capital gate"
            value={portfolio.live_enabled ? "ON" : "OFF"}
            accent={portfolio.live_enabled ? "up" : "warn"}
            icon={<ShieldCheck className="size-4" />}
            hint="WFO · holdout · paper · caps"
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-[1.55fr_1fr]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Pooled wallet</CardTitle>
                <CardDescription>One code path for backtest, paper and live — net of fees.</CardDescription>
              </div>
              <Badge variant="up">
                <Coins className="size-3" /> net of fees
              </Badge>
            </CardHeader>
            <CardContent>
              <AreaChart points={portfolio.equity_curve} height={244} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Allocation &amp; costs</CardTitle>
                <CardDescription>Capital split across decorrelated sleeves.</CardDescription>
              </div>
              <Layers className="size-4 text-quiet" />
            </CardHeader>
            <CardContent className="space-y-3.5">
              {portfolio.allocation.map((item: Allocation) => (
                <div key={item.strategy_id} className="space-y-1.5">
                  <div className="flex items-center justify-between text-[13px]">
                    <span className="font-medium text-foreground">{item.name}</span>
                    <span className="tabular text-muted">{Math.round(item.weight * 100)}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-iris/80"
                      style={{ width: `${Math.round(item.weight * 100)}%` }}
                    />
                  </div>
                  <div className="text-[11.5px] text-quiet">{item.venue}</div>
                </div>
              ))}
              <div className="space-y-1.5 border-t border-border/60 pt-3">
                {portfolio.costs.map((item: CostSlice) => (
                  <div key={item.category} className="flex items-center justify-between text-[12.5px]">
                    <span className="capitalize text-muted">{item.category}</span>
                    <span className="tabular text-foreground">{formatUsd(item.amount, 1)}</span>
                  </div>
                ))}
                <div className="flex items-center justify-between border-t border-border/60 pt-2 text-[13px] font-semibold">
                  <span>Total daily opex</span>
                  <span className="tabular">{formatUsd(costsTotal, 1)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Leaderboard */}
      <section id="leaderboard" className="space-y-4">
        <SectionHeader
          eyebrow="leaderboard"
          title="Every version earns its own standardized sleeve"
          aside={
            <Badge variant="iris">
              <Gauge className="size-3" /> ranked by deflated OOS Sharpe
            </Badge>
          }
        />
        <Card>
          <CardContent className="pt-5">
            <Table>
              <THead>
                <TR>
                  <TH>Strategy</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Sleeve</TH>
                  <TH className="text-right">Net</TH>
                  <TH className="text-right">D-Sharpe</TH>
                  <TH className="text-right">PBO</TH>
                  <TH>Lineage</TH>
                </TR>
              </THead>
              <TBody>
                {leaderboard.rows.map((row: LeaderboardRow) => (
                  <TR key={row.version_id}>
                    <TD>
                      <Link
                        href={`/strategy/${row.version_id}`}
                        className="font-medium text-foreground underline-offset-4 hover:text-iris-soft hover:underline"
                      >
                        {row.name}
                      </Link>
                    </TD>
                    <TD>
                      <Badge variant={statusVariant[row.status] ?? "muted"}>{row.status}</Badge>
                    </TD>
                    <TD className={`text-right tabular ${row.sleeve_return_pct >= 0 ? "text-up" : "text-down"}`}>
                      {formatPct(row.sleeve_return_pct)}
                    </TD>
                    <TD className={`text-right tabular ${row.net_pct >= 0 ? "text-up" : "text-down"}`}>
                      {formatPct(row.net_pct)}
                    </TD>
                    <TD className="text-right tabular text-foreground">{row.deflated_sharpe.toFixed(2)}</TD>
                    <TD className="text-right tabular text-muted">{row.pbo.toFixed(2)}</TD>
                    <TD className="text-[12px] text-quiet">{row.lineage}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </section>

      {/* Strategy spotlight */}
      <section id="strategy" className="space-y-4">
        <SectionHeader
          eyebrow="strategy spotlight"
          title={strategy.name}
          aside={
            <Badge variant="up">
              <ShieldCheck className="size-3" /> scorer-owned gates
            </Badge>
          }
        />
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Evidence</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {strategy.backtests.map((bt: Backtest) => (
                <div
                  key={bt.id}
                  className="flex items-center justify-between rounded-md border border-border/60 bg-surface-2/40 px-3 py-2.5"
                >
                  <div>
                    <div className="text-[13px] font-medium uppercase tracking-wide text-foreground">{bt.kind}</div>
                    <div className="text-[11.5px] text-quiet">
                      {bt.num_trades} trades · max DD {(bt.max_dd * 100).toFixed(1)}%
                    </div>
                  </div>
                  <Badge variant={bt.passed_gates ? "up" : "down"}>{bt.deflated_sharpe.toFixed(2)} dS</Badge>
                </div>
              ))}
              <p className="text-[12.5px] leading-relaxed text-muted">{strategy.notes_md}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Compiled artifact</CardTitle>
              <Badge variant="up">holdout · seen once · passed</Badge>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] leading-relaxed text-iris-soft">
                {strategy.generated_code}
              </pre>
              <Link
                href={`/strategy/${strategy.version_id}`}
                className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft hover:underline"
              >
                Full strategy detail <ArrowUpRight className="size-3.5" />
              </Link>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Console */}
      <section id="console" className="space-y-4">
        <SectionHeader
          eyebrow="console"
          title="Steer it in plain language"
          aside={
            <Badge variant="iris">
              <BrainCircuit className="size-3" /> LLM proposes · master disposes
            </Badge>
          }
        />
        <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
          <Card>
            <CardContent className="pt-5">
              <ConsoleBox />
            </CardContent>
          </Card>
          <div className="space-y-3">
            <Card>
              <CardHeader>
                <CardTitle>Recommendations</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {recommendations.map((rec: Recommendation) => (
                  <div key={rec.id} className="rounded-md border border-border/60 bg-surface-2/40 p-3">
                    <Badge variant="warn">{rec.kind.replace(/_/g, " ")}</Badge>
                    <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{rec.body}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Audit stream</CardTitle>
                <Radio className="size-4 text-info" />
              </CardHeader>
              <CardContent className="space-y-2.5">
                {events.map((event: Event) => (
                  <div key={event.id} className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[12.5px] font-medium text-foreground">{event.kind.replace(/_/g, " ")}</div>
                      <div className="text-[11px] text-quiet">
                        {event.actor} · {event.ref_type ?? "system"}
                      </div>
                    </div>
                    <span className="size-1.5 rounded-full bg-info/80" />
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      </section>
    </div>
  );
}
