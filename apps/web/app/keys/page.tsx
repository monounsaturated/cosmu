// Keys — the v18 top-level surface (mockup id=page-services): a read-only ledger of every provider/
// service key the machine uses. One row per env var: status-dot · Key · Service · Description · Location.
// SECURITY: the engine returns ONLY presence/status booleans per key — NEVER the value — so this is safe
// to render in the browser. Server-fetched from GET /settings/keys; honest "not connected" state when the
// engine is unreachable (we never pretend a key is set) and an honest empty state when it reports none.

import { KeyRound } from "lucide-react";
import { engineConfigured, getSettingsKeys } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { KeysTable, KeysLegend, countByStatus } from "@/components/keys/keys-table";

// Always render on-demand with fresh engine data — never statically pre-render (the engine may be offline
// at build time; on-demand lets the honest not-connected state handle it).
export const dynamic = "force-dynamic";

export default async function KeysPage() {
  const { keys, connected } = await getSettingsKeys();
  const counts = connected ? countByStatus(keys) : null;

  return (
    <div className="mx-auto max-w-[1000px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="keys"
        title="Services & keys"
        aside={
          connected && counts ? (
            <Badge variant={counts.missing > 0 ? "warn" : "up"}>
              {counts.connected} of {keys.length} connected
            </Badge>
          ) : null
        }
      />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="This indexes every provider key the machine uses — connected or not — and where to set it. The engine reports only whether each key is set, never its value. Connect the engine to see it."
        />
      ) : keys.length === 0 ? (
        <Card>
          <CardContent className="pt-5">
            <EmptyState
              title="No keys reported by the engine yet."
              hint="Once the engine starts up it publishes its key inventory here — connected, unverified, or missing. Values are never shown."
              icon={<KeyRound className="size-5" />}
            />
          </CardContent>
        </Card>
      ) : (
        // Matches the Costs ledger card: a single Card wrapping a dense, horizontally-scrolling table.
        <Card>
          <CardContent className="space-y-4 pt-5">
            <KeysLegend rows={keys} />
            <KeysTable rows={keys} />
          </CardContent>
        </Card>
      )}

      {/* Footnote — where keys live. View-only: nothing here is editable. */}
      <p className="px-0.5 text-[11.5px] leading-relaxed text-quiet">
        <code className="font-mono text-muted">.env.local</code> for local ·{" "}
        <code className="font-mono text-muted">Railway</code>/<code className="font-mono text-muted">Vercel</code>{" "}
        for deploy. View-only — values are never shown, only whether each key is set and verified.
      </p>
    </div>
  );
}
