// module: Settings → Keys. A read-only view of which provider keys are configured on the engine and
// what each unlocks. SECURITY: the engine returns a boolean `configured` per key, NEVER the value — so
// this is safe to render. Server-rendered from GET /settings/keys via data.ts. Honest offline state
// when the engine is unreachable: we never pretend a key is set.
//
// Layout: a coverage read-out (n of m plugged + a gauge), then keys grouped by requirement so a MISSING
// required key is impossible to miss. Within a group, configured keys settle below missing ones.

import { CheckCircle2, Circle, KeyRound } from "lucide-react";
import type { SettingsKeyRow } from "@/app/data";
import { Badge } from "@/components/ui/badge";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { GaugeBar } from "@/components/ui/viz";
import { cn } from "@/lib/utils";

// Requirement → group heading. The order of the keys here is the order groups render in.
const REQUIREMENT_GROUP: Record<SettingsKeyRow["requirement"], string> = {
  required: "Required",
  "live-only": "Live-only",
  optional: "Optional",
};

export function KeysPanel({
  keys,
  connected,
  configured,
}: {
  keys: SettingsKeyRow[];
  connected: boolean;
  configured: boolean;
}) {
  if (!connected) {
    return (
      <NotConnected
        configured={configured}
        what="This shows which provider keys are plugged in on the engine and what each unlocks. The engine reports only whether each key is set — never its value. Connect the engine to see it."
      />
    );
  }
  if (keys.length === 0) {
    return <EmptyState title="No keys reported by the engine yet." icon={<KeyRound className="size-5" />} />;
  }

  const plugged = keys.filter((k) => k.configured).length;
  const missingRequired = keys.filter((k) => k.requirement === "required" && !k.configured).length;

  // Group by requirement, missing-first within each group.
  const groups = (["required", "live-only", "optional"] as const)
    .map((req) => ({
      req,
      group: REQUIREMENT_GROUP[req],
      rows: keys
        .filter((k) => k.requirement === req)
        .sort((a, b) => Number(a.configured) - Number(b.configured)),
    }))
    .filter((g) => g.rows.length > 0);

  return (
    <div className="space-y-5">
      {/* Coverage read-out */}
      <div className="rounded-lg border border-border/60 bg-surface-2/30 p-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[12px] text-quiet">Keys configured on the engine</span>
          <span className="text-[13px] font-semibold tabular text-foreground">
            {plugged} <span className="text-quiet">of {keys.length}</span>
          </span>
        </div>
        <div className="mt-2">
          <GaugeBar value={plugged} max={keys.length} tone={missingRequired > 0 ? "warn" : "up"} />
        </div>
        <p className="mt-2.5 text-[11.5px] leading-relaxed text-quiet">
          {missingRequired > 0 ? (
            <span className="text-warn">
              {missingRequired} required key{missingRequired === 1 ? "" : "s"} still missing.{" "}
            </span>
          ) : (
            <span className="text-up">All required keys are plugged in. </span>
          )}
          Values are never shown — only whether each is set. Add or change them in the engine env (Railway), then redeploy.
        </p>
      </div>

      {/* Grouped key list */}
      {groups.map((g) => (
        <div key={g.req} className="space-y-2">
          <div className="flex items-center gap-2 px-0.5">
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">{g.group}</span>
            <span className="text-[11px] tabular text-quiet">
              {g.rows.filter((k) => k.configured).length}/{g.rows.length}
            </span>
          </div>
          <ul className="space-y-2">
            {g.rows.map((k) => (
              <KeyRow key={k.env_var} row={k} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function KeyRow({ row }: { row: SettingsKeyRow }) {
  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-lg border px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between",
        row.configured ? "border-up/30 bg-up/5" : "border-border/60 bg-surface-2/30"
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        {row.configured ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-up" />
        ) : (
          <Circle className="mt-0.5 size-4 shrink-0 text-quiet" />
        )}
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-medium text-foreground">{row.key}</span>
            <code className="rounded bg-background/60 px-1.5 py-0.5 font-mono text-[10.5px] text-quiet">
              {row.env_var}
            </code>
          </div>
          <p className="mt-0.5 text-[12px] leading-snug text-muted">{row.unlocks}</p>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5 pl-6 sm:pl-0">
        <Badge variant={row.cost === "free" ? "up" : "iris"}>{row.cost}</Badge>
        <Badge variant={row.configured ? "up" : "muted"}>{row.configured ? "configured" : "missing"}</Badge>
      </div>
    </li>
  );
}
