import { dashboardSchema } from "@cosmu/shared";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

const emptyDashboard = (backendError?: string) =>
  dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
    backendError,
    venueOverview: { live: null, testnet: null },
    accounts: [],
    bots: [],
    performanceSeries: [],
    recentRuns: [],
    recentExecutions: [],
    latestSnapshots: [],
    promptVersions: []
  });

export const getDashboard = async () => {
  const apiSecretKey = process.env.API_SECRET_KEY;

  if (!apiSecretKey) {
    return emptyDashboard("API_SECRET_KEY is required");
  }

  try {
    const response = await fetch(`${apiBaseUrl}/dashboard`, {
      cache: "no-store",
      signal: AbortSignal.timeout(25000),
      headers: {
        "x-api-key": apiSecretKey
      }
    });

    if (!response.ok) {
      throw new Error(`Dashboard request failed: ${response.status}`);
    }

    return dashboardSchema.parse(await response.json());
  } catch (error) {
    const message = error instanceof Error ? error.message : "Dashboard request failed";
    console.error("Dashboard fetch failed", error);
    return emptyDashboard(message);
  }
};
