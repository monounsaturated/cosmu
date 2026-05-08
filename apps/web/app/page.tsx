import Link from "next/link";
import { ArrowRight, BarChart3, Bot, Settings } from "lucide-react";
import { DashboardActions } from "./dashboard-actions";
import { PerformanceChart } from "./performance-chart";
import { RecentRunsTable } from "./run-detail-row";
import { BotTable } from "./bot-table";
import { AutoRefresh } from "./live-refresh";
import { LocalTime } from "./local-time";
import { KillAllBotsButton } from "./kill-all-bots";
import { VenueOverview } from "./venue-overview";
import { RecentExecutions } from "./recent-executions";
import { PortfolioState } from "./portfolio-state";
import { PromptSnapshots } from "./prompt-snapshots";
import { getDashboard } from "./dashboard-data";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const dashboard = await getDashboard();
  const lightBots = dashboard.bots.filter((bot) => (bot.workspaceMode ?? "light") === "light");
  const activeLightBots = lightBots.filter((bot) => bot.enabled).length;
  const totalLightPnl = lightBots.reduce((sum, bot) => sum + (bot.netPnlUsd ?? 0), 0);
  const recentFailures = dashboard.recentRuns.filter((run) => run.status === "failure").length;
  const liveExposure = dashboard.venueOverview.live?.allocatedAmount ?? 0;
  const testExposure = dashboard.venueOverview.testnet?.allocatedAmount ?? 0;
  const importantLightBots = [...lightBots]
    .sort((a, b) => {
      const aScore =
        (a.enabled ? 1000 : 0) +
        (a.latestError ? 700 : 0) +
        Math.abs(a.netPnlUsd ?? 0) +
        (a.currentPortfolioUsd ?? 0) / 100;
      const bScore =
        (b.enabled ? 1000 : 0) +
        (b.latestError ? 700 : 0) +
        Math.abs(b.netPnlUsd ?? 0) +
        (b.currentPortfolioUsd ?? 0) / 100;
      return bScore - aScore;
    })
    .slice(0, 6);
  const focusedDashboard = { ...dashboard, bots: importantLightBots };

  return (
    <main className="page page-wide">
      <AutoRefresh intervalMs={30000} />
      <section className="command-hero">
        <div>
          <p className="eyebrow">Command</p>
          <h1>Know what is running, why, and what can trade next.</h1>
          <p>
            One focused surface for creating agents, tracking performance, and tuning prompts, models,
            pairs, budget, cadence, and execution rules.
          </p>
        </div>
        <div className="hero-actions command-actions">
          <span className="badge badge-neutral">Updated <LocalTime value={dashboard.generatedAt} /></span>
          <div className="hero-action-row">
            <KillAllBotsButton />
            <DashboardActions hasNoBots={dashboard.bots.length === 0} />
          </div>
        </div>
      </section>

      <section className="product-flow" aria-label="Primary workflow">
        {[
          { href: "/bots", label: "Create", body: "Launch a lean paper agent", icon: Bot },
          { href: "/", label: "Monitor", body: "Runs, PnL, holdings, errors", icon: BarChart3 },
          { href: "/settings", label: "Tune", body: "Defaults, models, data toggles", icon: Settings }
        ].map((item) => {
          const Icon = item.icon;
          return (
            <Link href={item.href} className="flow-step" key={item.href}>
              <Icon size={18} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.body}</small>
              </span>
              <ArrowRight size={16} />
            </Link>
          );
        })}
      </section>

      <section className="metric-strip">
        <article>
          <span>Active agents</span>
          <strong>{activeLightBots}</strong>
          <small>{lightBots.length} configured</small>
        </article>
        <article>
          <span>Net PnL</span>
          <strong className={totalLightPnl >= 0 ? "value-green" : "value-red"}>
            {totalLightPnl >= 0 ? "+" : ""}${totalLightPnl.toFixed(2)}
          </strong>
          <small>Light workspace</small>
        </article>
        <article>
          <span>Recent failures</span>
          <strong className={recentFailures > 0 ? "value-red" : ""}>{recentFailures}</strong>
          <small>last dashboard window</small>
        </article>
        <article>
          <span>Latest runs</span>
          <strong>{dashboard.recentRuns.length}</strong>
          <small>audit ready</small>
        </article>
        <article>
          <span>Allocated</span>
          <strong>${(liveExposure + testExposure).toFixed(0)}</strong>
          <small>${liveExposure.toFixed(0)} live / ${testExposure.toFixed(0)} paper</small>
        </article>
      </section>

      <section className="command-grid">
        <VenueOverview venueOverview={dashboard.venueOverview} />
        <article className="panel">
          <h3>Recent Runs</h3>
          <p className="field-help">Open any row to inspect prompt, response, tools, and validator output.</p>
          {dashboard.recentRuns.length === 0 ? (
            <p className="muted">No runs yet. Create an agent, then run it from the table.</p>
          ) : (
            <RecentRunsTable runs={dashboard.recentRuns.slice(0, 5).map((r) => ({
              id: r.id,
              botName: r.botName,
              status: r.status,
              startedAt: r.startedAt,
              decisionMode: r.decisionMode,
              rationaleSummary: r.rationaleSummary
            }))} />
          )}
        </article>
      </section>

      <section className="focus-section">
        <BotTable
          dashboard={focusedDashboard}
          workspaceMode="light"
          title="Important agents"
          description="Active agents, recent errors, and meaningful exposure only. Open Agents for the full list."
          emptyMessage="No agents yet. Create one to start with a paper strategy."
          compact
          maxRows={6}
        />
      </section>

      <section className="stack command-stack">
        <article className="panel">
          <h3>Performance Comparison</h3>
          <PerformanceChart series={dashboard.performanceSeries} />
        </article>

        <RecentExecutions executions={dashboard.recentExecutions.slice(0, 6)} />
        <PortfolioState snapshots={dashboard.latestSnapshots.slice(0, 6)} />
        <PromptSnapshots versions={dashboard.promptVersions.slice(0, 6)} />
      </section>
    </main>
  );
}
