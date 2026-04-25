import { dashboardSchema } from "@cosmu/shared";
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

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export const dynamic = "force-dynamic";

const emptyDashboard = () =>
  dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
    venueOverview: { live: null, testnet: null },
    bots: [],
    performanceSeries: [],
    recentRuns: [],
    recentExecutions: [],
    latestSnapshots: [],
    promptVersions: []
  });

const getDashboard = async () => {
  try {
    const apiSecretKey = process.env.API_SECRET_KEY;
    if (!apiSecretKey) {
      throw new Error("API_SECRET_KEY is required");
    }

    const response = await fetch(`${apiBaseUrl}/dashboard`, {
      cache: "no-store",
      headers: {
        "x-api-key": apiSecretKey
      }
    });

    if (!response.ok) {
      throw new Error(`Dashboard request failed: ${response.status}`);
    }

    return dashboardSchema.parse(await response.json());
  } catch (error) {
    console.error("Dashboard fetch failed, rendering empty state", error);
    return emptyDashboard();
  }
};

export default async function HomePage() {
  const dashboard = await getDashboard();

  return (
    <main className="page">
      <AutoRefresh intervalMs={30000} />
      <section className="hero">
        <div>
          <p className="muted">Cosmu V1</p>
          <h1>Autonomous Loop Dashboard</h1>
          <p>One bot, one real loop, clear decision and execution traceability.</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "8px" }}>
          <KillAllBotsButton />
          <span className="badge">Updated <LocalTime value={dashboard.generatedAt} /></span>
          <DashboardActions hasNoBots={dashboard.bots.length === 0} />
        </div>
      </section>

      <VenueOverview venueOverview={dashboard.venueOverview} />

      <section className="grid" style={{ display: 'block', marginBottom: '32px' }}>
        <BotTable dashboard={dashboard} />
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
