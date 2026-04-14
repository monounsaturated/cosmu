import Link from "next/link";
import { dashboardSchema } from "@cosmu/shared";
import { BotTable } from "../bot-table";
import { DashboardActions } from "../dashboard-actions";

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
    if (!apiSecretKey) throw new Error("API_SECRET_KEY is required");

    const response = await fetch(`${apiBaseUrl}/dashboard`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey }
    });

    if (!response.ok) {
      throw new Error(`Dashboard request failed: ${response.status}`);
    }

    return dashboardSchema.parse(await response.json());
  } catch (error) {
    console.error("Bots page dashboard fetch failed", error);
    return emptyDashboard();
  }
};

export default async function BotsPage() {
  const dashboard = await getDashboard();

  return (
    <main className="page">
      <section className="hero">
        <div>
          <Link href="/" className="muted" style={{ display: "inline-block", marginBottom: "16px", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
          <h1>Bots</h1>
          <p>Compare bots quickly, then click a row to open full details.</p>
        </div>
        <DashboardActions hasNoBots={dashboard.bots.length === 0} botCount={dashboard.bots.length} />
      </section>

      <BotTable dashboard={dashboard} />
    </main>
  );
}
