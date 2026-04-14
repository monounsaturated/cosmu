import { dashboardSchema } from "@cosmu/shared";
import { BotControls } from "./bot-controls";
import { DashboardActions } from "./dashboard-actions";
import { PerformanceChart } from "./performance-chart";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

export const dynamic = "force-dynamic";

const emptyDashboard = () =>
  dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
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
      <section className="hero">
        <div>
          <p className="muted">Cosmu V1</p>
          <h1>Autonomous Loop Dashboard</h1>
          <p>One bot, one real loop, clear decision and execution traceability.</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "8px" }}>
          <span className="badge">Updated {new Date(dashboard.generatedAt).toLocaleString()}</span>
          <DashboardActions hasNoBots={dashboard.bots.length === 0} botCount={dashboard.bots.length} />
        </div>
      </section>

      <section className="grid">
        {dashboard.bots.map((bot) => (
          <article className="panel bot-card" key={bot.id}>
            <div className="bot-header">
              <div>
                <h2>#{bot.botNumber} {bot.name}</h2>
              </div>
              <span className={`status-dot ${bot.enabled ? "status-active" : "status-inactive"}`} />
            </div>
            <div className="bot-badges">
              <span className="badge">{bot.venue === "binance" ? "Binance France" : bot.venue}</span>
              <span className={`badge ${bot.mode === "live" ? "badge-live" : ""}`}>{bot.mode}</span>
              <span className="badge">{bot.frequencyMinutes}m</span>
              <span className="badge">{bot.assetClass}</span>
            </div>
            <div className="bot-meta">
              <p><span className="label">Prompt</span> {bot.promptVersionLabel}</p>
              <p><span className="label">Model</span> {bot.modelProfileName}</p>
              <p><span className="label">Running since</span> {new Date(bot.startedAt).toLocaleDateString()}</p>
              <p><span className="label">Days live</span> {bot.daysRunning.toFixed(1)}</p>
              <p><span className="label">Runs</span> {bot.runCount}</p>
              <p><span className="label">Total trades</span> {bot.tradeCount}</p>
              <p><span className="label">Avg trades/day</span> {bot.avgTradesPerDay.toFixed(2)}</p>
              <p><span className="label">Portfolio</span> {bot.currentPortfolioUsd !== null ? `$${bot.currentPortfolioUsd.toFixed(2)}` : "—"}</p>
              <p><span className="label">Gross PnL</span> {bot.grossPnlUsd !== null ? `$${bot.grossPnlUsd.toFixed(2)}` : "—"}</p>
              <p><span className="label">Net PnL</span> {bot.netPnlUsd !== null ? `$${bot.netPnlUsd.toFixed(2)}` : "—"}</p>
              <p><span className="label">Fees</span> {bot.totalFeesUsd !== null ? `$${bot.totalFeesUsd.toFixed(2)}` : "—"}</p>
              <p><span className="label">Credibility</span> {bot.sampleQuality}</p>
              <p><span className="label">Last run</span> {bot.lastRunStatus ?? "never"}</p>
              <p><span className="label">Decision</span> {bot.latestDecisionSummary ?? "—"}</p>
              {bot.latestError && (
                <p className="error-text"><span className="label">Error</span> {bot.latestError}</p>
              )}
            </div>
            <BotControls botId={bot.id} enabled={bot.enabled} />
          </article>
        ))}
      </section>

      <section className="stack">
        <article className="panel">
          <h3>Performance Comparison</h3>
          <PerformanceChart series={dashboard.performanceSeries} />
        </article>

        <article className="panel">
          <h3>Recent Runs</h3>
          {dashboard.recentRuns.length === 0 ? (
            <p className="muted">No runs yet. Use Run Now to trigger the first one.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Bot</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Mode</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.recentRuns.map((run) => (
                  <tr key={run.id}>
                    <td>{run.botName}</td>
                    <td><span className={`badge badge-${run.status}`}>{run.status}</span></td>
                    <td>{new Date(run.startedAt).toLocaleString()}</td>
                    <td>{run.decisionMode ?? "-"}</td>
                    <td>{run.rationaleSummary ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
                  <p className="label">Holdings</p>
                  <ul>
                    {item.snapshot.balances.map((balance) => (
                      <li key={balance.asset}>
                        {balance.asset}: {(balance.free + balance.locked).toFixed(6)}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="panel">
          <h3>Prompt History</h3>
          {dashboard.promptVersions.length === 0 ? (
            <p className="muted">No prompts yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Prompt</th>
                  <th>Version</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.promptVersions.map((promptVersion) => (
                  <tr key={`${promptVersion.promptName}-${promptVersion.version}`}>
                    <td>{promptVersion.promptName}</td>
                    <td>{promptVersion.version}</td>
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
