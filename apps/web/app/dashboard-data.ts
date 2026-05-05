import { dashboardSchema } from "@cosmu/shared";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

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

export const getDashboard = async () => {
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
