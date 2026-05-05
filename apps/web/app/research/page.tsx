import {
  researchCandidateSchema,
  researchDataSourceSchema,
  researchExperimentSchema
} from "@cosmu/shared";
import { ResearchConsole } from "./research-console";
import { BotTable } from "../bot-table";
import { getDashboard } from "../dashboard-data";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export const dynamic = "force-dynamic";

async function fetchApi(path: string) {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) return null;
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey }
    });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export default async function ResearchPage({
  searchParams
}: {
  searchParams?: Promise<{ command?: string }>;
}) {
  const params = await searchParams;
  const [experimentsRaw, dataSourcesRaw, candidatesRaw, dashboard] = await Promise.all([
    fetchApi("/research/experiments"),
    fetchApi("/research/data-sources"),
    fetchApi("/research/candidates"),
    getDashboard()
  ]);

  const experiments = researchExperimentSchema.array().catch([]).parse(experimentsRaw?.experiments ?? []);
  const dataSources = researchDataSourceSchema.array().catch([]).parse(dataSourcesRaw?.dataSources ?? []);
  const candidates = researchCandidateSchema.array().catch([]).parse(candidatesRaw?.candidates ?? []);

  return (
    <main className="page page-wide">
      <ResearchConsole
        initialCommand={params?.command ?? ""}
        initialExperiments={experiments}
        initialDataSources={dataSources}
        initialCandidates={candidates}
      />
      <div style={{ marginTop: "20px" }}>
        <BotTable
          dashboard={dashboard}
          title="Research Agents"
          description="Research and paper candidates use the same benchmark view as Light. Today this includes the operational agents; paper agents will appear here as Research creates them."
          emptyMessage="No research agents yet. Run a hypothesis to create a paper candidate."
        />
      </div>
    </main>
  );
}

