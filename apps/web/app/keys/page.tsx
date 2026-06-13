// Keys — the v13/v14 top-level surface: a read-only index of every provider/service key, whether it's
// configured on the engine, and what each unlocks. SECURITY: the engine returns ONLY a boolean
// `configured` per key — never the value — so this is safe to render in the browser. Server-fetched from
// GET /settings/keys; honest "not connected" state when the engine is unreachable (never pretends a key is set).

import { engineConfigured, getSettingsKeys } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { KeysPanel } from "@/components/settings/keys-panel";

// Always render on-demand with fresh engine data — never statically pre-render (the engine may be offline
// at build time; on-demand lets the honest not-connected state handle it).
export const dynamic = "force-dynamic";

export default async function KeysPage() {
  const { keys, connected } = await getSettingsKeys();
  const setCount = keys.filter((k) => k.configured).length;

  return (
    <div className="mx-auto max-w-[1000px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="keys"
        title="Services & keys"
        aside={connected ? <Badge variant="muted">{setCount} of {keys.length} connected</Badge> : null}
      />
      {/* Reuses the secure KeysPanel (status only, never values), grouped by requirement with a coverage gauge. */}
      <KeysPanel keys={keys} connected={connected} configured={engineConfigured} />
    </div>
  );
}
