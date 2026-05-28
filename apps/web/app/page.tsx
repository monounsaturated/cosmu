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
          <p className="eyebrow">Trading desk</p>
          <h1>Agent balance sheet</h1>
          <p>
            Accounts, active risk, PnL, and execution flow in one focused dashboard.
          </p>
        </div>
        <div className="hero-actions command-actions">
          <span className="badge badge-neutral">Updated <LocalTime value={dashboard.generatedAt} /></span>
          <DashboardActions hasNoBots={dashboard.bots.length === 0} dashboardUnavailable={Boolean(dashboard.backendError)} />
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
          <small>{dashboard.accounts.filter((account) => account.connected).length}/{dashboard.accounts.length} connected</small>
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
          <span>Recent failures</span>
          <strong className={recentFailures > 0 ? "value-red" : ""}>{recentFailures}</strong>
          <small>last dashboard window</small>
        </article>
      </section>

      <section className="command-grid">
        <VenueOverview accounts={dashboard.accounts} venueOverview={dashboard.venueOverview} />
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

        <RecentExecutions executions={dashboard.recentExecutions} />
        <PortfolioState snapshots={dashboard.latestSnapshots} />
        <PromptSnapshots versions={dashboard.promptVersions} />
      </section>
    </main>
  );
}
