// Keys — the v18 top-level surface (mockup id=page-services): a read-only ledger of every provider/
// service key the machine uses. One bento `.key-tbl` row per env var: status-dot · Key · Service ·
// Description · Location.
//
// SECURITY: the engine returns ONLY presence/status booleans per key — NEVER the value — so this is safe
// to render in the browser. Server-fetched from GET /settings/keys; honest <NotConnected/> when the
// engine is unreachable (we never pretend a key is set) and an honest <EmptyState/> when it reports none.

import { Suspense } from "react";
import { engineConfigured, getSettingsKeys } from "../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { KeysTable, KeysLegend, keyedCounts } from "@/components/keys/keys-table";

// Always render on-demand with fresh engine data — never statically pre-render (the engine may be offline
// at build time; on-demand lets the honest not-connected state handle it).
export const dynamic = "force-dynamic";

export default function KeysPage() {
  return (
    <Page>
      <Toolbar title="Keys" />
      <Suspense fallback={<div className="skel" style={{ height: 360 }} />}>
        <KeysData />
      </Suspense>
    </Page>
  );
}

async function KeysData() {
  const { keys, connected } = await getSettingsKeys();

  if (!connected) {
    return (
      <NotConnected
        configured={engineConfigured}
        what="This indexes every provider key the machine uses — connected or not — and where to set it. The engine reports only whether each key is set, never its value. Connect the engine to see it."
      />
    );
  }

  if (keys.length === 0) {
    return (
      <div className="card">
        <div className="card-body">
          <EmptyState
            title="No keys reported by the engine yet."
            hint="Once the engine starts up it publishes its key inventory here — connected, unverified, or missing. Values are never shown."
          />
        </div>
      </div>
    );
  }

  const { connected: connCount, total } = keyedCounts(keys);

  return (
    <div className="card">
      <div className="card-hdr ck-hd">
        <span className="card-lbl">
          Keys · {connCount} of {total} connected
        </span>
        <KeysLegend />
      </div>
      <div className="card-body">
        <KeysTable rows={keys} />
        <div className="costs-note">
          View only. Each key goes in <code>.env.local</code> for local runs and in its host (Railway ·
          Vercel) for the deployed engine/web. The host name shows{" "}
          <span style={{ color: "var(--up)", fontWeight: 600 }}>green</span> when present, red when the
          deployed host is missing it, amber when unverified. No values are shown.
        </div>
      </div>
    </div>
  );
}
