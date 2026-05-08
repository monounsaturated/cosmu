"use client";

import { useState } from "react";
import type { DashboardPayload } from "@cosmu/shared";

type SnapshotEntry = DashboardPayload["latestSnapshots"][number];

const formatUsd = (value: number | null | undefined, signed = false) => {
  if (value === null || value === undefined) return "—";
  const formatted = Math.abs(value).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  });
  if (!signed) return value < 0 ? `-${formatted}` : formatted;
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
};

export function PortfolioState({ snapshots, initialRows = 6 }: { snapshots: SnapshotEntry[]; initialRows?: number }) {
  const [showAll, setShowAll] = useState(false);
  const visibleSnapshots = showAll ? snapshots : snapshots.slice(0, initialRows);

  if (snapshots.length === 0) {
    return (
      <article className="panel">
        <h3>Portfolio state</h3>
        <p className="muted">No portfolio snapshots yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <div className="panel-table-header">
        <div>
          <h3>Portfolio state</h3>
          <p className="field-help">Current virtual wallet per agent.</p>
        </div>
        <span className="badge badge-neutral">{snapshots.length}</span>
      </div>

      <div className={`data-table-scroll ${showAll ? "data-table-scroll-expanded" : ""}`}>
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Total</th>
              <th>Net PnL</th>
              <th>Holdings</th>
            </tr>
          </thead>
          <tbody>
            {visibleSnapshots.map((item) => (
              <tr key={item.botId}>
                <td data-label="Agent" className="table-truncate">{item.botName}</td>
                <td data-label="Total"><strong>{formatUsd(item.snapshot.totalUsdValue)}</strong></td>
                <td data-label="Net PnL">
                  <span className={item.snapshot.netPnlUsd && item.snapshot.netPnlUsd > 0 ? "value-green" : item.snapshot.netPnlUsd && item.snapshot.netPnlUsd < 0 ? "value-red" : ""}>
                    {formatUsd(item.snapshot.netPnlUsd, true)}
                  </span>
                </td>
                <td data-label="Holdings">
                  <details className="holdings-details">
                    <summary>{item.snapshot.balances.length} assets</summary>
                    <div>
                      {item.snapshot.balances.map((balance) => (
                        <span key={balance.asset}>
                          <strong>{balance.asset}</strong>
                          {(balance.free + balance.locked).toFixed(6)}
                        </span>
                      ))}
                    </div>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {snapshots.length > initialRows ? (
        <button type="button" className="btn btn-secondary btn-small table-expand-toggle" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Show less" : `Show all ${snapshots.length}`}
        </button>
      ) : null}
    </article>
  );
}
