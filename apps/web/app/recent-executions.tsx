"use client";

import { useState } from "react";
import type { DashboardPayload } from "@cosmu/shared";

type Execution = DashboardPayload["recentExecutions"][number];

export function RecentExecutions({ executions, initialRows = 6 }: { executions: Execution[]; initialRows?: number }) {
  const [highlightedRun, setHighlightedRun] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const visibleExecutions = showAll ? executions : executions.slice(0, initialRows);
  if (executions.length === 0) {
    return (
      <article className="panel">
        <h3>Executions</h3>
        <p className="muted">No executions yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <div className="panel-table-header">
        <div>
          <h3>Executions</h3>
          <p className="field-help">Latest fills, fees, and order status.</p>
        </div>
        <span className="badge badge-neutral">{executions.length}</span>
      </div>
      <div className={`data-table-scroll ${showAll ? "data-table-scroll-expanded" : ""}`}>
        <table className="table table-compact">
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
            {visibleExecutions.map((execution) => (
              <tr
                key={`${execution.runId}-${execution.symbol}-${execution.requestedQuantity}`}
                style={{
                  background: highlightedRun === execution.runId ? "color-mix(in srgb, var(--accent) 8%, transparent)" : undefined,
                  cursor: "default"
                }}
                onMouseEnter={() => setHighlightedRun(execution.runId)}
                onMouseLeave={() => setHighlightedRun(null)}
              >
                <td data-label="Run">
                  <span className="badge badge-neutral mono-badge">
                    {execution.runId.slice(0, 8)}
                  </span>
                </td>
                <td data-label="Symbol">{execution.symbol}</td>
                <td data-label="Side"><span className={`badge badge-${execution.side}`}>{execution.side}</span></td>
                <td data-label="Type">{execution.orderType}</td>
                <td data-label="Status"><span className={`badge badge-${execution.status}`}>{execution.status}</span></td>
                <td data-label="Qty">{execution.executedQuantity ?? execution.requestedQuantity}</td>
                <td data-label="Avg Price">{execution.averageFillPrice ? `$${execution.averageFillPrice}` : "—"}</td>
                <td data-label="Notional">{execution.executedNotionalUsd ? `$${execution.executedNotionalUsd.toFixed(2)}` : "—"}</td>
                <td data-label="Fee">
                  {execution.feeAmount ?? 0} {execution.feeAsset ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {executions.length > initialRows ? (
        <button type="button" className="btn btn-secondary btn-small table-expand-toggle" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Show less" : `Show all ${executions.length}`}
        </button>
      ) : null}
    </article>
  );
}
