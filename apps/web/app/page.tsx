import { DashboardActions } from "./dashboard-actions";
import { PerformanceChart } from "./performance-chart";
import { RecentRunsTable } from "./run-detail-row";
import { BotTable } from "./bot-table";
import { AutoRefresh } from "./live-refresh";
import { LocalTime } from "./local-time";
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
  const totalAccountBalance = dashboard.accounts.reduce((sum, account) => sum + account.accountBalance, 0);
  const totalAllocated = dashboard.accounts.reduce((sum, account) => sum + account.allocatedAmount, 0);
  const freeCapacity = dashboard.accounts.reduce((sum, account) => sum + account.spareAmount, 0);
  const connectedVenues = dashboard.accounts.filter((account) => account.connected).length;
  const llmHourlyUsd = dashboard.llmSpendEstimate?.estimatedHourlyUsd ?? 0;
  const llmDailyUsd = dashboard.llmSpendEstimate?.estimatedDailyUsd ?? 0;
  return (
    <main className="page page-wide">
      <AutoRefresh intervalMs={30000} />
      <section className="command-hero agents-hero">
        <div>
          <p className="eyebrow">Agents</p>
          <h1>Run, inspect, and control every agent.</h1>
          <p>
            One command center for agent status, portfolio exposure, recent runs, and emergency controls.
          </p>
        </div>
        <div className="hero-actions command-actions">
          <span className="badge badge-neutral">Updated <LocalTime value={dashboard.generatedAt} /></span>
          <DashboardActions
            hasNoBots={dashboard.bots.length === 0}
            activeBotCount={dashboard.bots.filter((bot) => bot.enabled).length}
            dashboardUnavailable={Boolean(dashboard.backendError)}
          />
        </div>
      </section>

      {dashboard.backendError && (
        <section className="panel dashboard-error-state">
          <strong>Dashboard backend unavailable</strong>
          <p>The agent list could not be loaded from the API. The app is showing an error instead of an empty state.</p>
          <code>{dashboard.backendError}</code>
        </section>
      )}

      <section className="metric-strip">
        <article>
          <span>Active agents</span>
          <strong>{activeLightBots}</strong>
          <small>{lightBots.length} configured</small>
        </article>
        <article className="metric-card-emphasis">
          <span>Equity</span>
          <strong>{totalAccountBalance.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}</strong>
          <small>{connectedVenues}/{dashboard.accounts.length} venues connected</small>
        </article>
        <article>
          <span>Allocated</span>
          <strong>{totalAllocated.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}</strong>
          <small>across live, paper, future accounts</small>
        </article>
        <article>
          <span>Free cash</span>
          <strong className={freeCapacity < 0 ? "value-red" : "value-green"}>
            {freeCapacity.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
          </strong>
          <small>unallocated capacity</small>
        </article>
        <article>
          <span>Net PnL</span>
          <strong className={totalLightPnl >= 0 ? "value-green" : "value-red"}>
            {totalLightPnl >= 0 ? "+" : ""}${totalLightPnl.toFixed(2)}
          </strong>
          <small>Light workspace</small>
        </article>
        <article>
          <span>LLM burn</span>
          <strong>{llmHourlyUsd.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })}/h</strong>
          <small>{llmDailyUsd.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}/day estimate</small>
        </article>
        <article>
          <span>Recent failures</span>
          <strong className={recentFailures > 0 ? "value-red" : ""}>{recentFailures}</strong>
          <small>last dashboard window</small>
        </article>
      </section>

      <BotTable
        dashboard={dashboard}
        workspaceMode="light"
        title="Agents"
        description="The main operating table. Search, sort, run, stop, and open an agent from one place."
        emptyMessage="No agents yet. Create one to start with a paper strategy."
        defaultSortField="created"
        defaultSortOrder="desc"
        showCreatedByDefault
      />

      <section className="command-grid">
        <VenueOverview
          accounts={dashboard.accounts}
          venueOverview={dashboard.venueOverview}
          marketDataStatus={dashboard.marketDataStatus}
        />
        <article className="panel">
          <div className="panel-table-header">
            <div>
              <h3>Recent runs</h3>
              <p className="field-help">Expand rows for prompts, tool calls, and validation.</p>
            </div>
            <span className="badge badge-neutral">{dashboard.recentRuns.length}</span>
          </div>
          {dashboard.recentRuns.length === 0 ? (
            <p className="muted">No runs yet. Create an agent, then run it from the table.</p>
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
      </section>

      <section className="stack command-stack">
        <article className="panel">
          <h3>Performance Comparison</h3>
          <PerformanceChart series={dashboard.performanceSeries} />
        </article>

        <RecentExecutions executions={dashboard.recentExecutions} />
        <PortfolioState snapshots={dashboard.latestSnapshots} />
        <PromptSnapshots versions={dashboard.promptVersions} />
      </section>
    </main>
  );
}
