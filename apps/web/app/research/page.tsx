import {
  datasetSchema,
  researchMemorySchema,
  researchCandidateSchema,
  researchDataSourceSchema,
  researchExperimentSchema,
  researchSessionSchema
} from "@cosmu/shared";
import { ResearchConsole } from "./research-console";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export const dynamic = "force-dynamic";

async function fetchApi(path: string) {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) return null;
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey },
      signal: AbortSignal.timeout(6000)
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
  const pageData = await fetchApi("/research/page-data");

  const experiments = researchExperimentSchema.array().catch([]).parse(pageData?.experiments ?? []);
  const dataSources = researchDataSourceSchema.array().catch([]).parse(pageData?.dataSources ?? []);
  const candidates = researchCandidateSchema.array().catch([]).parse(pageData?.candidates ?? []);
  const datasets = datasetSchema.array().catch([]).parse(pageData?.datasets ?? []);
  const sessions = researchSessionSchema.array().catch([]).parse(pageData?.sessions ?? []);
  const memories = researchMemorySchema.array().catch([]).parse(pageData?.memories ?? []);

  return (
    <main className="page page-wide">
      <ResearchConsole
        initialCommand={params?.command ?? ""}
        initialExperiments={experiments}
        initialDataSources={dataSources}
        initialCandidates={candidates}
        initialDatasets={datasets}
        initialSessions={sessions}
        initialMemories={memories}
      />
    </main>
  );
}

