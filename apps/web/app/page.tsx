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

  return (
    <main className="page page-wide">
      <AutoRefresh intervalMs={30000} />
      <section className="hero hero-cockpit">
        <div>
          <p className="eyebrow">Cosmu Light</p>
          <h1>Agent trading, kept calm.</h1>
          <p>
            Research, trader, validator, execution, and guardian in one focused cockpit.
            Signals feed the loop; every prompt and tool call stays inspectable.
          </p>
        </div>
        <div className="hero-actions">
          <span className="badge badge-neutral">Updated <LocalTime value={dashboard.generatedAt} /></span>
          <div className="hero-action-row">
            <KillAllBotsButton />
            <DashboardActions hasNoBots={dashboard.bots.length === 0} />
          </div>
        </div>
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
      </section>

      <VenueOverview venueOverview={dashboard.venueOverview} />

      <section className="focus-section">
        <BotTable
          dashboard={dashboard}
          workspaceMode="light"
          title="Light Agents"
          description="Lean operational loop: research → trader → validator → execution on Binance. Light is intentionally separate from Research and Pro — Research bots and Pro bots will not appear here."
          emptyMessage="No Light agents yet. Use Create Bot to add a fast iteration agent."
        />
      </section>

      <section className="stack">
        <article className="panel">
          <h3>Performance Comparison</h3>
          <PerformanceChart series={dashboard.performanceSeries} />
        </article>

        <article className="panel">
          <h3>Recent Runs</h3>
          <p className="field-help">Click a row to see the exact prompt sent and LLM response.</p>
          {dashboard.recentRuns.length === 0 ? (
            <p className="muted">No runs yet. Use Run Now to trigger the first one.</p>
          ) : (
            <RecentRunsTable runs={dashboard.recentRuns.map((r) => ({
              id: r.id,
              botName: r.botName,
              status: r.status,
              startedAt: r.startedAt,
              decisionMode: r.decisionMode,
              rationaleSummary: r.rationaleSummary
            }))} />
          )}
        </article>

        <RecentExecutions executions={dashboard.recentExecutions} />
        <PortfolioState snapshots={dashboard.latestSnapshots} />
        <PromptSnapshots versions={dashboard.promptVersions} />
      </section>
    </main>
  );
}
