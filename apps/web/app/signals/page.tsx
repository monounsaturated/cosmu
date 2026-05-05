import { rawObservationSchema, standardizedSignalSchema } from "@cosmu/shared";
import { SignalConsole } from "./signal-console";

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

export default async function SignalsPage() {
  const [signalsRaw, observationsRaw] = await Promise.all([
    fetchApi("/signals?limit=80"),
    fetchApi("/signals/observations?limit=40")
  ]);

  const signals = standardizedSignalSchema.array().catch([]).parse(signalsRaw?.signals ?? []);
  const observations = rawObservationSchema.array().catch([]).parse(observationsRaw?.observations ?? []);

  return (
    <main className="page page-wide">
      <SignalConsole initialSignals={signals} initialObservations={observations} />
    </main>
  );
}
