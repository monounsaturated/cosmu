import { dashboardSchema } from "@cosmu/shared";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

const getDashboard = async () => {
  const response = await fetch(`${apiBaseUrl}/dashboard`, {
    cache: "no-store"
  });

  if (!response.ok) {
    throw new Error(`Dashboard request failed: ${response.status}`);
  }

  return dashboardSchema.parse(await response.json());
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
        <span className="badge">Updated {new Date(dashboard.generatedAt).toLocaleString()}</span>
      </section>

      <section className="grid">
        {dashboard.bots.map((bot) => (
          <article className="panel" key={bot.id}>
            <h2>{bot.name}</h2>
            <p className="muted">{bot.slug}</p>
            <p>
              <span className="badge">{bot.enabled ? "enabled" : "disabled"}</span>{" "}
              <span className="badge">{bot.mode}</span>{" "}
              <span className="badge">{bot.frequencyMinutes}m</span>
            </p>
            <p>Prompt: {bot.promptVersionLabel}</p>
            <p>Model: {bot.modelProfileName}</p>
            <p>Last run: {bot.lastRunStatus ?? "never"}</p>
            <p>Decision: {bot.latestDecisionSummary ?? "No decisions yet"}</p>
            <p>Error: {bot.latestError ?? "None"}</p>
          </article>
        ))}
      </section>

      <section className="stack">
        <article className="panel">
          <h3>Recent Runs</h3>
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
                  <td>{run.status}</td>
                  <td>{new Date(run.startedAt).toLocaleString()}</td>
                  <td>{run.decisionMode ?? "-"}</td>
                  <td>{run.rationaleSummary ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>

        <article className="panel">
          <h3>Recent Executions</h3>
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
                  <td>{execution.side}</td>
                  <td>{execution.orderType}</td>
                  <td>{execution.status}</td>
                  <td>{execution.executedQuantity ?? execution.requestedQuantity}</td>
                  <td>
                    {execution.feeAmount ?? 0} {execution.feeAsset ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>

        <article className="panel">
          <h3>Latest Portfolio State</h3>
          <div className="grid">
            {dashboard.latestSnapshots.map((item) => (
              <div key={item.botName} className="panel">
                <h3>{item.botName}</h3>
                <p>Total USD value: {item.snapshot.totalUsdValue.toFixed(2)}</p>
                <p>Gross PnL: {item.snapshot.grossPnlUsd?.toFixed(2) ?? "-"}</p>
                <p>Net PnL: {item.snapshot.netPnlUsd?.toFixed(2) ?? "-"}</p>
                <p>Holdings:</p>
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
        </article>

        <article className="panel">
          <h3>Prompt History</h3>
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
        </article>
      </section>
    </main>
  );
}
