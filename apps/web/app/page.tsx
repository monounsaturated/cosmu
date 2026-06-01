import { ArrowRight, Coins, Gauge, PieChart, Receipt, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { demoBenchmarkCurve, getEvents, getLeaderboard, getPortfolio, getRecommendations } from "./data";
import type { CostSlice, Event, LeaderboardRow, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { Tooltip } from "@/components/ui/tooltip";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { EquityCurve } from "@/components/charts/equity-curve";
import { AllocationChart } from "@/components/charts/allocation-chart";
import { CostBars } from "@/components/charts/cost-bars";
import { CrossAssetGate } from "@/components/research/cross-asset-gate";
import { formatPct, formatSigned, formatUsd } from "@/lib/utils";

const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  paper: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

// Sleeve-% vs pooled-wallet — the one explanation that disambiguates the two money layers.
const SLEEVE_VS_POOLED = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-foreground">Sleeve %</span> — each strategy&apos;s own net-of-fee return on its
      standardized capital sleeve, judged in isolation.
    </p>
    <p>
      <span className="font-semibold text-foreground">Pooled wallet</span> — the single aggregate across every funded
      sleeve. This is the headline number.
    </p>
  </div>
);

export default async function OverviewPage() {
  const [{ portfolio, demo }, leaderboard, recommendations, events] = await Promise.all([
    getPortfolio(),
    getLeaderboard(),
    getRecommendations(),
    getEvents()
  ]);

  // Honest: do not invent a track record. We only compute a return when there is a real curve.
  const hasTrackRecord = portfolio.equity_curve.length >= 2;
  const equity = portfolio.equity_curve.at(-1)?.value ?? 0;
  const start = portfolio.equity_curve[0]?.value ?? 0;
  const returnPct = hasTrackRecord && start ? ((equity - start) / start) * 100 : 0;
  const costsTotal = portfolio.costs.reduce((sum: number, c: CostSlice) => sum + c.amount, 0);
  const up = returnPct >= 0;

  // One source of truth for "what kind of money is this?" — drives every label on the page.
  const mode = moneyMode({ demo, live: portfolio.live_enabled });

  // BTC buy-and-hold benchmark overlay: only the clearly-labelled demo series exists offline.
  // When the engine is reachable we don't fabricate one (no field on the contract yet).
  const benchmark = demo ? demoBenchmarkCurve : undefined;

  // Which strategies are working: top few funded/working sleeves by net %, never the killed ones.
  const working = (leaderboard.rows as LeaderboardRow[])
    .filter((r) => r.status !== "killed")
    .sort((a, b) => b.net_pct - a.net_pct)
    .slice(0, 4);

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      {demo ? (
        <div className="flex items-center gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <span className="size-1.5 shrink-0 rounded-full bg-warn" />
          Engine unreachable — showing labelled demo data. These numbers are not a real track record.
        </div>
      ) : null}

      {/* Headline money number — are we making money? */}
      <section className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">
              net return · after fees
            </span>
            <MoneyState mode={mode} />
          </div>
          {hasTrackRecord ? (
            <>
              <div className={`mt-1.5 text-[2.75rem] font-semibold leading-none tracking-tight tabular sm:text-5xl ${up ? "text-up" : "text-down"}`}>
                {formatPct(returnPct)}
              </div>
              <div className="mt-2 flex items-center gap-2 text-[13px] text-muted">
                {up ? <TrendingUp className="size-4 text-up" /> : <TrendingDown className="size-4 text-down" />}
                <span className={up ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span>
                <span className="text-quiet">total profit · since inception</span>
              </div>
            </>
          ) : (
            <>
              <div className="mt-1.5 text-[2.75rem] font-semibold leading-none tracking-tight tabular text-quiet sm:text-5xl">—</div>
              <div className="mt-2 text-[13px] text-quiet">No paper track record yet. Numbers appear once the engine starts trading on paper.</div>
            </>
          )}
        </div>
      </section>

      {/* Compact KPI row */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Pooled wallet"
          value={hasTrackRecord ? formatUsd(equity) : "—"}
          accent="iris"
          icon={<Coins className="size-4" />}
          hint={<span className="inline-flex items-center gap-1 text-quiet">aggregate <Tooltip content={SLEEVE_VS_POOLED} /></span>}
        />
        <Stat
          label="Total profit"
          value={hasTrackRecord ? <span className={up ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span> : "—"}
          accent={up ? "up" : "down"}
        />
        <Stat label="Opex vs alpha" value={portfolio.costs.length ? `${Math.round(portfolio.opex_vs_alpha * 100)}%` : "—"} accent="warn" icon={<Gauge className="size-4" />} />
        <Stat label="Daily opex" value={portfolio.costs.length ? formatUsd(costsTotal, 0) : "—"} accent="iris" />
      </section>

      {/* Pooled wallet equity chart — interactive: time range, drawdown shading, benchmark overlay */}
      <section>
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <CardTitle>Pooled wallet</CardTitle>
              <Tooltip content={SLEEVE_VS_POOLED} />
            </div>
          </CardHeader>
          <CardContent>
            <EquityCurve points={portfolio.equity_curve} benchmark={benchmark} mode={mode} height={260} />
          </CardContent>
        </Card>
      </section>

      {/* Allocation + costs — where the pooled capital sits and what it costs to run */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <CardTitle className="flex items-center gap-1.5">
                <PieChart className="size-4 text-iris-soft" /> Allocation
              </CardTitle>
              <Tooltip content="How the pooled wallet is split across funded strategy sleeves, by weight and capital." />
            </div>
            <MoneyState mode={mode} withInfo={false} />
          </CardHeader>
          <CardContent>
            <AllocationChart allocation={portfolio.allocation} height={220} />
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
              <p className="text-[12.5px] text-quiet">No cost data yet. Opex appears once the engine starts spending on research.</p>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Which strategies are working — top few by net %, detail lives in Research */}
      <section>
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <CardTitle>Working strategies</CardTitle>
              <Tooltip content={SLEEVE_VS_POOLED} />
            </div>
            <Link
              href="/research"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
            >
              All strategies <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-2">
            {working.length === 0 ? (
              <p className="text-[12.5px] text-quiet">No surviving strategies yet. Survivors appear here once a sleeve clears the gates.</p>
            ) : (
              working.map((row) => (
                <Link
                  key={row.version_id}
                  href={`/strategy/${row.version_id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2.5 transition-colors hover:border-border hover:bg-surface-2/55"
                >
                  <div className="min-w-0">
                    <div className="truncate text-[12.5px] font-medium text-foreground">{row.name}</div>
                    <div className="text-[11px] text-quiet">sleeve · net of fees</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2.5">
                    <span className={`tabular text-[13px] font-medium ${row.net_pct >= 0 ? "text-up" : "text-down"}`}>
                      {formatPct(row.net_pct)}
                    </span>
                    <Badge variant={statusVariant[row.status] ?? "muted"}>{row.status}</Badge>
                  </div>
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </section>

      {/* Needs you + how the machine is working (recent activity) */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Needs you</CardTitle>
            <Link
              href="/console"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
            >
              Open console <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {recommendations.length === 0 ? (
              <p className="text-[12.5px] text-quiet">Nothing waiting on you right now.</p>
            ) : (
              recommendations.map((rec: Recommendation) => (
                <div key={rec.id} className="rounded-md border border-border/60 bg-surface-2/40 p-3">
                  <Badge variant="warn">{rec.kind.replace(/_/g, " ")}</Badge>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{rec.body}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>What the machine did</CardTitle>
            <Link
              href="/console"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
            >
              Full stream <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {events.map((event: Event) => (
              <div key={event.id} className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-[12.5px] font-medium text-foreground">{event.kind.replace(/_/g, " ")}</div>
                  <div className="text-[11px] text-quiet">
                    {event.actor} · {event.ref_type ?? "system"}
                  </div>
                </div>
                <span className="size-1.5 shrink-0 rounded-full bg-info/80" />
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {/* Cross-asset gate status */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">research signal</div>
          <Link
            href="/research"
            className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
          >
            All research <ArrowRight className="size-3.5" />
          </Link>
        </div>
        <CrossAssetGate compact />
      </section>
    </div>
  );
}
