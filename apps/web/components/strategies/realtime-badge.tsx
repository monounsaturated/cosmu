// module: realtime-worker pulse badge (realtime-data-lane P3), Iris Bento. Purpose: make worker staleness
// VISIBLE — "a stale heartbeat is a badge, not a silent failure". Invariants: hidden when the worker is
// disabled (off is the honest default, not an alarm); gold when enabled-but-silent/stale; up/green when
// fresh. Display-only; reads the generated contract type. Carries a data-tip for the detail.

import type { RealtimeStatusResponse } from "@cosmu/contracts-ts";

export function RealtimeBadge({ realtime }: { realtime: RealtimeStatusResponse }) {
  if (!realtime.enabled) return null; // OFF by design — the cron lane is the data path; nothing to warn about
  if (realtime.status === "fresh") {
    return (
      <span className="badge badge-up" data-tip="Realtime worker heartbeat is fresh">
        <span className="run-dot" /> realtime live
      </span>
    );
  }
  const detail =
    realtime.status === "never"
      ? "worker enabled but no heartbeat recorded yet"
      : `last heartbeat ${Math.round((realtime.seconds_since_heartbeat ?? 0) / 60)}m ago`;
  return (
    <span className="badge" style={{ color: "var(--gold)", borderColor: "oklch(0.82 0.14 85 / 0.32)" }} data-tip={detail}>
      <span className="run-dot" style={{ background: "var(--gold)" }} /> realtime stale
    </span>
  );
}
