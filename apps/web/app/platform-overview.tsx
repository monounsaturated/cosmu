import { Database, GitBranch, Radar } from "lucide-react";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

const fetchApi = async <T,>(path: string): Promise<T | null> => {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) return null;
  try {
    const res = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
      headers: { "x-api-key": apiSecretKey }
    });
    if (!res.ok) return null;
    return await res.json() as T;
  } catch {
    return null;
  }
};

export async function PlatformOverview() {
  const [sources, indexes, agents] = await Promise.all([
    fetchApi<{ sources: unknown[] }>("/sources"),
    fetchApi<{ indexes: unknown[] }>("/indexes"),
    fetchApi<{ agents: unknown[] }>("/agents/registry")
  ]);

  const rows = [
    { icon: Database, label: "Sources", value: sources?.sources.length ?? 0, detail: "read-only inputs" },
    { icon: Radar, label: "Indexes", value: indexes?.indexes.length ?? 0, detail: "signal views" },
    { icon: GitBranch, label: "Agents", value: agents?.agents.length ?? 0, detail: "declared roles" }
  ];

  return (
    <article className="panel platform-overview">
      <div className="panel-table-header">
        <div>
          <h3>Agentic platform</h3>
          <p className="field-help">Data sources, indexes, and agent roles are explicit modules.</p>
        </div>
      </div>
      <div className="platform-overview-grid">
        {rows.map((row) => {
          const Icon = row.icon;
          return (
            <div key={row.label} className="platform-overview-item">
              <Icon size={18} />
              <span>{row.label}</span>
              <strong>{row.value}</strong>
              <small>{row.detail}</small>
            </div>
          );
        })}
      </div>
    </article>
  );
}
