import { dashboardSchema } from "@cosmu/shared";
import { DashboardActions } from "./dashboard-actions";
import { PerformanceChart } from "./performance-chart";
import { RecentRunsTable } from "./run-detail-row";
import { BotTable } from "./bot-table";
import { AutoRefresh } from "./live-refresh";

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
          <span className="badge">Updated {new Date(dashboard.generatedAt).toLocaleString()}</span>
          <DashboardActions hasNoBots={dashboard.bots.length === 0} />
        </div>
      </section>

      <section style={{ marginBottom: "32px", display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {dashboard.venueOverview.live && (
          <div className="panel venue-group" style={{ flex: "1 1 340px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <span className="status-dot status-active" style={{ width: "8px", height: "8px" }} />
              <span className="label" style={{ fontSize: "13px", color: "#34d399" }}>Live</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
              <div>
                <p className="label">Account Balance</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.live.accountBalance.toFixed(2)}</h2>
              </div>
              <div>
                <p className="label">Allocated to Bots</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.live.allocatedAmount.toFixed(2)}</h2>
              </div>
              <div>
                <p className="label">Spare</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.live.spareAmount.toFixed(2)}</h2>
              </div>
            </div>
          </div>
        )}
        {dashboard.venueOverview.testnet && (
          <div className="panel venue-group" style={{ flex: "1 1 340px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <span className="status-dot status-inactive" style={{ width: "8px", height: "8px" }} />
              <span className="label" style={{ fontSize: "13px", color: "#a1a1aa" }}>Testnet</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
              <div>
                <p className="label">Account Balance</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.testnet.accountBalance.toFixed(2)}</h2>
              </div>
              <div>
                <p className="label">Allocated to Bots</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.testnet.allocatedAmount.toFixed(2)}</h2>
              </div>
              <div>
                <p className="label">Spare</p>
                <h2 style={{ margin: "4px 0", fontSize: "20px" }}>${dashboard.venueOverview.testnet.spareAmount.toFixed(2)}</h2>
              </div>
            </div>
          </div>
        )}
        {!dashboard.venueOverview.live && !dashboard.venueOverview.testnet && (
          <div className="panel" style={{ flex: 1 }}>
            <p className="muted">No venue data available.</p>
          </div>
        )}
      </section>

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

        <article className="panel">
          <h3>Recent Executions</h3>
          {dashboard.recentExecutions.length === 0 ? (
            <p className="muted">No executions yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Qty</th>
                  <th>Fee</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.recentExecutions.map((execution) => (
                  <tr key={`${execution.runId}-${execution.symbol}-${execution.requestedQuantity}`}>
                    <td>{execution.symbol}</td>
                    <td><span className={`badge badge-${execution.side}`}>{execution.side}</span></td>
                    <td>{execution.orderType}</td>
                    <td><span className={`badge badge-${execution.status}`}>{execution.status}</span></td>
                    <td>{execution.executedQuantity ?? execution.requestedQuantity}</td>
                    <td>
                      {execution.feeAmount ?? 0} {execution.feeAsset ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </article>

        <article className="panel">
          <h3>Latest Portfolio State</h3>
          {dashboard.latestSnapshots.length === 0 ? (
            <p className="muted">No portfolio snapshots yet.</p>
          ) : (
            <div className="grid">
              {dashboard.latestSnapshots.map((item) => (
                <div key={item.botName} className="panel">
                  <h3>{item.botName}</h3>
                  <p><span className="label">Total USD</span> ${item.snapshot.totalUsdValue.toFixed(2)}</p>
                  <p><span className="label">Gross PnL</span> {item.snapshot.grossPnlUsd?.toFixed(2) ?? "—"}</p>
                  <p><span className="label">Net PnL</span> {item.snapshot.netPnlUsd?.toFixed(2) ?? "—"}</p>
                  <details style={{ marginTop: '8px' }}>
                    <summary className="label clickable" style={{ display: 'inline-block' }}>View Holdings ({item.snapshot.balances.length})</summary>
                    <ul style={{ marginTop: '8px' }}>
                      {item.snapshot.balances.map((balance) => (
                        <li key={balance.asset}>
                          {balance.asset}: {(balance.free + balance.locked).toFixed(6)}
                        </li>
                      ))}
                    </ul>
                  </details>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <h3>Prompt Snapshots</h3>
          {dashboard.promptVersions.length === 0 ? (
            <p className="muted">No prompts yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Prompt</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.promptVersions.map((promptVersion) => (
                  <tr key={`${promptVersion.promptName}-${promptVersion.version}`}>
                    <td>{promptVersion.label}</td>
                    <td>{new Date(promptVersion.createdAt).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </article>
      </section>
    </main>
  );
}
