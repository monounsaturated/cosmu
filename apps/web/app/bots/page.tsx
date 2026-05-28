import { BotTable } from "../bot-table";
import { DashboardActions } from "../dashboard-actions";
import { getDashboard } from "../dashboard-data";

export const dynamic = "force-dynamic";

export default async function BotsPage() {
  const dashboard = await getDashboard();
  const active = dashboard.bots.filter((bot) => bot.enabled).length;

  return (
    <main className="page page-wide">
      <section className="hero hero-compact">
        <div>
          <p className="eyebrow">Agents</p>
          <h1>Build and tune every agent.</h1>
          <p>
            Create, inspect, and compare the core Cosmu trading agents from one table.
          </p>
        </div>
        <div className="hero-actions">
          <span className="badge badge-neutral">{active} active</span>
          <DashboardActions hasNoBots={dashboard.bots.length === 0} />
        </div>
      </section>

      <BotTable
        dashboard={dashboard}
        title="All agents"
        description="Every strategy in one sortable table. Click a row for run history, positions, prompts, and controls."
        emptyMessage="No agents yet. Create one to start testing a strategy."
        defaultSortField="created"
        defaultSortOrder="desc"
        showCreatedByDefault
      />
    </main>
  );
}
