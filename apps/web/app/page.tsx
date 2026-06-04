import { ArrowRight, Coins, Gauge, LineChart, ListChecks, MessageSquare, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getAutonomyStatus, getEvents, getInboxQueue, getIntelligence, getLeaderboard, getMind, getOverview, getPopulation, getRecommendations } from "./data";
import type { CostSlice, LeaderboardRow, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { Tooltip } from "@/components/ui/tooltip";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { EquityCurve } from "@/components/charts/equity-curve";
import { LifecycleStrip } from "@/components/ui/lifecycle-strip";
import { AutonomyPanel } from "@/components/autonomy/autonomy-panel";
import { NeedsYouInbox } from "@/components/autonomy/needs-you-inbox";
import { SystemIntelligence } from "@/components/intelligence/system-intelligence";
import { RightNow } from "@/components/overview/right-now";
import { WhatNext } from "@/components/overview/what-next";
import { IdeaInbox } from "@/components/overview/idea-inbox";
import { DataFreshness } from "@/components/overview/data-freshness";
import { TRACK_VS_AGGREGATE } from "@/lib/shared-content";
import { formatPct, formatSigned, formatUsd } from "@/lib/utils";

const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  forward_test: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

export default async function OverviewPage() {
  const [
    { overview, connected },
    { leaderboard },
    { items: recommendations, connected: recConnected },
    { events },
    { status: autonomy, connected: autonomyConnected },
    { intelligence, connected: intelConnected },
    { population },
    { mind },
    { items: queuedIdeas, connected: inboxConnected }
  ] = await Promise.all([
    getOverview(),
    getLeaderboard(),
    getRecommendations(),
    getEvents(),
    getAutonomyStatus(),
    getIntelligence(),
    getPopulation(),
    getMind(),
    getInboxQueue()
  ]);

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">overview</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">Are we making money?</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="The Overview shows your net return across forward-tests and what needs you. Connect the engine to see live numbers."
        />
      </div>
    );
  }

  const hasTrackRecord = overview.equity_curve.length >= 2;
  const equity = overview.equity_curve.at(-1)?.value ?? 0;
  const start = overview.equity_curve[0]?.value ?? 0;
  const returnPct = hasTrackRecord && start ? ((equity - start) / start) * 100 : 0;
  const costsTotal = overview.costs.reduce((sum: number, c: CostSlice) => sum + c.amount, 0);
  const up = returnPct >= 0;
  const mode = moneyMode({ live: overview.live_enabled });

  const working = (leaderboard.rows as LeaderboardRow[])
    .filter((r) => r.status !== "killed")
    .sort((a, b) => b.net_pct - a.net_pct)
    .slice(0, 4);

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      {/* Headline money number */}
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
                <span className={up ? "text-up" : "text-down"}>{formatSigned(overview.pnl_net)}</span>
                <span className="text-quiet">total profit · since inception</span>
              </div>
            </>
          ) : (
            <>
              <div className="mt-1.5 text-[2.75rem] font-semibold leading-none tracking-tight tabular text-quiet sm:text-5xl">—</div>
              <div className="mt-2 text-[13px] text-quiet">No track record yet. Numbers appear once the engine starts trading in sim.</div>
            </>
          )}
        </div>
      </section>

      {/* KPI row */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Net equity"
          value={hasTrackRecord ? formatUsd(equity) : "—"}
          accent="iris"
          icon={<Coins className="size-4" />}
          hint={<span className="inline-flex items-center gap-1 text-quiet">across forward-tests <Tooltip content={TRACK_VS_AGGREGATE} /></span>}
        />
        <Stat
          label="Total profit"
          value={hasTrackRecord ? <span className={up ? "text-up" : "text-down"}>{formatSigned(overview.pnl_net)}</span> : "—"}
          accent={up ? "up" : "down"}
        />
        <Stat label="Opex vs alpha" value={overview.costs.length ? `${Math.round(overview.opex_vs_alpha * 100)}%` : "—"} accent="warn" icon={<Gauge className="size-4" />} />
        <Stat label="Daily opex" value={overview.costs.length ? formatUsd(costsTotal, 0) : "—"} accent="iris" />
      </section>

      {/* What to do next — 1–3 concrete suggestions derived purely from real engine state. */}
      <WhatNext
        population={population}
        leaderboard={leaderboard.rows as LeaderboardRow[]}
        recommendations={recommendations as Recommendation[]}
        autonomy={autonomy}
        dataFreshness={intelligence.data_freshness}
        hasTrackRecord={hasTrackRecord}
        returnPct={returnPct}
      />

      {/* Right now — the command-center band: engine, population, Mind, what needs you, latest events. */}
      <RightNow
        connected={connected}
        autonomy={autonomy}
        population={population}
        mind={mind}
        recommendations={recommendations}
        events={events}
      />

      {/* Idea inbox (drop a strategy vibe → gated spec) + data freshness (is the system fed?). */}
      <section className="grid gap-3 lg:grid-cols-2">
        <IdeaInbox initial={queuedIdeas} connected={inboxConnected} configured={engineConfigured} />
        <DataFreshness sources={intelligence.data_freshness} connected={intelConnected} />
      </section>

      {/* How Cosmu works — the four stages, clickable. Clears up Lab / Forward-test / Live at a glance. */}
      <LifecycleStrip />

      {/* Equity chart */}
      <section>
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <LineChart className="size-4 text-iris-soft" />
              <CardTitle>Net across forward-tests</CardTitle>
              <Tooltip content={TRACK_VS_AGGREGATE} />
            </div>
            <Link href="/forward-test" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline">
              Open Forward-test <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            <EquityCurve points={overview.equity_curve} mode={mode} height={260} />
          </CardContent>
        </Card>
      </section>

      {/* System intelligence — is the machine getting smarter? */}
      <SystemIntelligence intelligence={intelligence} connected={intelConnected} />

      {/* What needs me + autonomy controls */}
      <section className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <MessageSquare className="size-4 text-iris-soft" /> Needs you
            </CardTitle>
            <Link
              href="/steer"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
            >
              <MessageSquare className="size-3.5" /> Steer <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            <NeedsYouInbox initial={recommendations} connected={recConnected} configured={engineConfigured} />
          </CardContent>
        </Card>

        <AutonomyPanel initial={autonomy} connected={autonomyConnected} configured={engineConfigured} />
      </section>

      {/* Working Versions — the survivors currently proving themselves on their own tracks. */}
      <section>
        <Card>
          <CardHeader>
            <div className="flex min-w-0 items-center gap-1.5">
              <ListChecks className="size-4 text-iris-soft" />
              <CardTitle>Working Versions</CardTitle>
              <Tooltip content={TRACK_VS_AGGREGATE} />
            </div>
            <Link
              href="/strategies"
              className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
            >
              All Strategies <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            {working.length === 0 ? (
              <EmptyState
                title="No surviving Versions yet."
                hint="Authored strategies that clear the deterministic Gate land here and start a forward-test track. Author one from the Lab or Claude Code, or wait for the next autonomous cycle."
              />
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">{working.map((row) => (
                <Link
                  key={row.version_id}
                  href={`/strategy/${row.version_id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2.5 transition-colors hover:border-border hover:bg-surface-2/55"
                >
                  <div className="min-w-0">
                    <div className="truncate text-[12.5px] font-medium text-foreground">{row.name}</div>
                    <div className="text-[11px] text-quiet">net of fees</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2.5">
                    <span className={`tabular text-[13px] font-medium ${row.net_pct >= 0 ? "text-up" : "text-down"}`}>
                      {formatPct(row.net_pct)}
                    </span>
                    <Badge variant={statusVariant[row.status] ?? "muted"}>{row.status}</Badge>
                  </div>
                </Link>
              ))}</div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
