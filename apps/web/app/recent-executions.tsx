"use client";

import { useState } from "react";
import type { DashboardPayload } from "@cosmu/shared";

type Execution = DashboardPayload["recentExecutions"][number];

export function RecentExecutions({ executions }: { executions: Execution[] }) {
  const [highlightedRun, setHighlightedRun] = useState<string | null>(null);
  if (executions.length === 0) {
    return (
      <article className="panel">
        <h3>Recent Executions</h3>
        <p className="muted">No executions yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <h3>Recent Executions</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Run</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Type</th>
            <th>Status</th>
            <th>Qty</th>
            <th>Avg Price</th>
            <th>Notional</th>
            <th>Fee</th>
          </tr>
        </thead>
        <tbody>
          {executions.map((execution) => (
            <tr
              key={`${execution.runId}-${execution.symbol}-${execution.requestedQuantity}`}
              style={{
                background: highlightedRun === execution.runId ? "#27272a44" : undefined,
                cursor: "default"
              }}
              onMouseEnter={() => setHighlightedRun(execution.runId)}
              onMouseLeave={() => setHighlightedRun(null)}
            >
              <td>
                <span className="badge badge-neutral" style={{ fontSize: "10px", fontFamily: "monospace" }}>
                  {execution.runId.slice(0, 8)}
                </span>
              </td>
              <td>{execution.symbol}</td>
              <td><span className={`badge badge-${execution.side}`}>{execution.side}</span></td>
              <td>{execution.orderType}</td>
              <td><span className={`badge badge-${execution.status}`}>{execution.status}</span></td>
              <td>{execution.executedQuantity ?? execution.requestedQuantity}</td>
              <td>{execution.averageFillPrice ? `$${execution.averageFillPrice}` : "—"}</td>
              <td>{execution.executedNotionalUsd ? `$${execution.executedNotionalUsd.toFixed(2)}` : "—"}</td>
              <td>
                {execution.feeAmount ?? 0} {execution.feeAsset ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}
