import { ArrowRight, Coins, Gauge, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { getEvents, getPortfolio, getRecommendations } from "./data";
import type { CostSlice, Event, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { AreaChart } from "@/components/charts/area-chart";
import { CrossAssetGate } from "@/components/research/cross-asset-gate";
import { formatPct, formatSigned, formatUsd } from "@/lib/utils";

export default async function OverviewPage() {
  const [{ portfolio, demo }, recommendations, events] = await Promise.all([
    getPortfolio(),
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

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 px-5 py-7 lg:px-7">
      {demo ? (
        <div className="flex items-center gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <span className="size-1.5 rounded-full bg-warn" />
          Engine unreachable — showing labelled demo data. These numbers are not a real track record.
        </div>
      ) : null}

      {/* Headline money number */}
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">net return · after fees · paper</div>
          {hasTrackRecord ? (
            <>
              <div className={`mt-1 text-5xl font-semibold tracking-tight tabular ${up ? "text-up" : "text-down"}`}>
                {formatPct(returnPct)}
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-[13px] text-muted">
                {up ? <TrendingUp className="size-4 text-up" /> : <TrendingDown className="size-4 text-down" />}
                <span className={up ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span>
                <span className="text-quiet">since inception</span>
              </div>
            </>
          ) : (
            <>
              <div className="mt-1 text-5xl font-semibold tracking-tight tabular text-quiet">—</div>
              <div className="mt-1.5 text-[13px] text-quiet">No paper track record yet. Numbers appear once the engine starts trading on paper.</div>
            </>
          )}
        </div>
        <Badge variant={portfolio.live_enabled ? "up" : "warn"}>
          <ShieldCheck className="size-3" /> Live capital {portfolio.live_enabled ? "ON" : "OFF"}
        </Badge>
      </section>

      {/* Compact KPI row */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Pooled paper equity" value={hasTrackRecord ? formatUsd(equity) : "—"} accent="iris" icon={<Coins className="size-4" />} />
        <Stat
          label="Net P&L (after costs)"
          value={hasTrackRecord ? <span className={up ? "text-up" : "text-down"}>{formatSigned(portfolio.pnl_net)}</span> : "—"}
          accent={up ? "up" : "down"}
        />
        <Stat label="Opex vs alpha" value={portfolio.costs.length ? `${Math.round(portfolio.opex_vs_alpha * 100)}%` : "—"} accent="warn" icon={<Gauge className="size-4" />} />
        <Stat label="Daily opex" value={portfolio.costs.length ? formatUsd(costsTotal, 0) : "—"} accent="iris" />
      </section>

      {/* One equity chart */}
      <section>
        <Card>
          <CardHeader>
            <CardTitle>Pooled wallet</CardTitle>
            <Badge variant="up">
              <Coins className="size-3" /> net of fees
            </Badge>
          </CardHeader>
          <CardContent>
            {hasTrackRecord ? (
              <AreaChart points={portfolio.equity_curve} height={240} />
            ) : (
              <div className="flex h-[240px] flex-col items-center justify-center gap-1.5 text-center">
                <Coins className="size-5 text-quiet" />
                <div className="text-[13px] text-muted">No live data yet</div>
                <div className="max-w-sm text-[11.5px] text-quiet">
                  The pooled wallet curve renders once the engine has a real paper portfolio.
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Needs you + recent activity */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Needs you</CardTitle>
            <Link
              href="/console"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft hover:underline"
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
            <CardTitle>Recent activity</CardTitle>
            <Link
              href="/console"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft hover:underline"
            >
              Full stream <ArrowRight className="size-3.5" />
            </Link>
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
      </section>

      {/* Cross-asset gate status */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">research signal</div>
          <Link
            href="/research"
            className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft hover:underline"
          >
            All research <ArrowRight className="size-3.5" />
          </Link>
        </div>
        <CrossAssetGate compact />
      </section>
    </div>
  );
}
