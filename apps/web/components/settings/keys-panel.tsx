// module: Settings → Keys. A read-only view of which provider keys are configured on the engine and
// what each unlocks. SECURITY: the engine returns a boolean `configured` per key, NEVER the value —
// so this is safe to render. Server-rendered from GET /settings/keys via data.ts. Honest offline state
// when the engine is unreachable: we never pretend a key is set.

import { CheckCircle2, Circle, KeyRound } from "lucide-react";
import type { SettingsKeyRow } from "@/app/data";
import { Badge } from "@/components/ui/badge";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { cn } from "@/lib/utils";

function RequirementBadge({ requirement }: { requirement: SettingsKeyRow["requirement"] }) {
  const map = {
    required: { variant: "down" as const, label: "required" },
    "live-only": { variant: "warn" as const, label: "live-only" },
    optional: { variant: "muted" as const, label: "optional" }
  };
  const { variant, label } = map[requirement];
  return <Badge variant={variant}>{label}</Badge>;
}

export function KeysPanel({ keys, connected, configured }: { keys: SettingsKeyRow[]; connected: boolean; configured: boolean }) {
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

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-quiet">
        <span className="font-medium text-foreground">{plugged}</span> of {keys.length} keys configured. Values are never
        shown — only whether each is set on the engine. Add or change them in the engine env (Railway), then redeploy.
      </p>
      <ul className="space-y-2">
        {keys.map((k) => (
          <li
            key={k.env_var}
            className={cn(
              "flex flex-col gap-2 rounded-lg border px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between",
              k.configured ? "border-up/30 bg-up/5" : "border-border/60 bg-surface-2/30"
            )}
          >
            <div className="flex min-w-0 items-start gap-2.5">
              {k.configured ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-up" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-quiet" />
              )}
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium text-foreground">{k.key}</span>
                  <code className="rounded bg-background/60 px-1.5 py-0.5 font-mono text-[10.5px] text-quiet">{k.env_var}</code>
                </div>
                <p className="mt-0.5 text-[12px] leading-snug text-muted">{k.unlocks}</p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5 pl-6 sm:pl-0">
              <RequirementBadge requirement={k.requirement} />
              <Badge variant={k.cost === "free" ? "up" : "iris"}>{k.cost}</Badge>
              <Badge variant={k.configured ? "up" : "muted"}>{k.configured ? "configured" : "missing"}</Badge>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
