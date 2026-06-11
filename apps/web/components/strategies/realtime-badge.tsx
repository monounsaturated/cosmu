// module: realtime-worker pulse badge (realtime-data-lane P3). Purpose: make worker staleness VISIBLE —
// "a stale heartbeat is a badge, not a silent failure" (epic §3). Invariants: hidden when the worker is
// disabled (off is the honest default, not an alarm); amber when enabled-but-silent/stale; green when fresh.
// Display-only; reads the generated contract type.

import { Radio, TriangleAlert } from "lucide-react";
import type { RealtimeStatusResponse } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";

export function RealtimeBadge({ realtime }: { realtime: RealtimeStatusResponse }) {
  if (!realtime.enabled) return null; // OFF by design — the cron lane is the data path; nothing to warn about
  if (realtime.status === "fresh") {
    return (
      <Badge variant="up" title="Realtime worker heartbeat is fresh">
        <Radio className="size-3" /> realtime live
      </Badge>
    );
  }
  const detail =
    realtime.status === "never"
      ? "worker enabled but no heartbeat recorded yet"
      : `last heartbeat ${Math.round((realtime.seconds_since_heartbeat ?? 0) / 60)}m ago`;
  return (
    <Badge variant="warn" title={detail}>
      <TriangleAlert className="size-3" /> realtime stale
    </Badge>
  );
}
