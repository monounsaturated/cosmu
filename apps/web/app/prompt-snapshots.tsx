"use client";

import { useState } from "react";
import type { DashboardPayload } from "@cosmu/shared";
import { LocalTime } from "./local-time";

type PromptVersion = DashboardPayload["promptVersions"][number];

export function PromptSnapshots({ versions, initialRows = 6 }: { versions: PromptVersion[]; initialRows?: number }) {
  const [showAll, setShowAll] = useState(false);
  const visibleVersions = showAll ? versions : versions.slice(0, initialRows);

  if (versions.length === 0) {
    return (
      <article className="panel">
        <h3>Prompt versions</h3>
        <p className="muted">No prompts yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <div className="panel-table-header">
        <div>
          <h3>Prompt versions</h3>
          <p className="field-help">Recent research prompt snapshots.</p>
        </div>
        <span className="badge badge-neutral">{versions.length}</span>
      </div>
      <div className={`data-table-scroll ${showAll ? "data-table-scroll-expanded" : ""}`}>
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Prompt</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {visibleVersions.map((pv) => (
              <tr key={`${pv.promptName}-${pv.version}`}>
                <td data-label="Prompt" className="table-truncate">{pv.label}</td>
                <td data-label="Created"><LocalTime value={pv.createdAt} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {versions.length > initialRows ? (
        <button type="button" className="btn btn-secondary btn-small table-expand-toggle" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Show less" : `Show all ${versions.length}`}
        </button>
      ) : null}
    </article>
  );
}
