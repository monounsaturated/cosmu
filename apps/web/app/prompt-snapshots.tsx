import type { DashboardPayload } from "@cosmu/shared";
import { LocalTime } from "./local-time";

type PromptVersion = DashboardPayload["promptVersions"][number];

export function PromptSnapshots({ versions }: { versions: PromptVersion[] }) {
  if (versions.length === 0) {
    return (
      <article className="panel">
        <h3>Prompt Snapshots</h3>
        <p className="muted">No prompts yet.</p>
      </article>
    );
  }

  return (
    <article className="panel">
      <h3>Prompt Snapshots</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Prompt</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((pv) => (
            <tr key={`${pv.promptName}-${pv.version}`}>
              <td>{pv.label}</td>
              <td><LocalTime value={pv.createdAt} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}
