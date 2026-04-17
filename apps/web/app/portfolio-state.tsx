import type { DashboardPayload } from "@cosmu/shared";

type SnapshotEntry = DashboardPayload["latestSnapshots"][number];

export function PortfolioState({ snapshots }: { snapshots: SnapshotEntry[] }) {
  if (snapshots.length === 0) {
    return (
      <article className="panel">
        <h3>Latest Portfolio State</h3>
        <p className="muted">No portfolio snapshots yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <h3>Latest Portfolio State</h3>
      <div className="grid">
        {snapshots.map((item) => (
          <div key={item.botId} className="panel">
            <h3>{item.botName}</h3>
            <p><span className="label">Total USD</span> ${item.snapshot.totalUsdValue.toFixed(2)}</p>
            <p><span className="label">Gross PnL</span> {item.snapshot.grossPnlUsd?.toFixed(2) ?? "—"}</p>
            <p><span className="label">Net PnL</span> {item.snapshot.netPnlUsd?.toFixed(2) ?? "—"}</p>
            <details style={{ marginTop: "8px" }}>
              <summary className="label clickable" style={{ display: "inline-block" }}>
                View Holdings ({item.snapshot.balances.length})
              </summary>
              <ul style={{ marginTop: "8px" }}>
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
    </article>
  );
}
