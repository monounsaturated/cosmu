// Indexes — the operator-defined, standardized, deterministically-scored signal registry (the page the
// operator asked for: "shows all the created indexes"). An index is a point-in-time numeric series scored the
// SAME way every pass (frozen transform) from a topic, a prompt rubric, or a bucket of social accounts; later,
// strategies key off it. This surface lists them with their current value + health; the detail digs in.
//
// HONESTY: not-connected → the engine-not-connected state; available:false → the honest "registry not active
// yet, apply the migration" state (never fabricated rows); empty → "define one". Every number is real.

import { Suspense } from "react";
import { engineConfigured, getIndexes } from "../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected } from "@/components/ui/honest-state";
import { IndexesTable } from "@/components/indexes/indexes-table";

export const dynamic = "force-dynamic";

export default function IndexesPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Indexes" />
            <div className="skel" style={{ height: 360 }} />
          </>
        }
      >
        <IndexesData />
      </Suspense>
    </Page>
  );
}

async function IndexesData() {
  const { indexes, connected } = await getIndexes();

  if (!connected) {
    return (
      <>
        <Toolbar title="Indexes" />
        <NotConnected
          configured={engineConfigured}
          what="Indexes are standardized, deterministically-scored signal series (topic · prompt rubric · social-account bucket) that strategies key off. They appear here once the engine is connected — no demo rows."
        />
      </>
    );
  }

  if (!indexes.available) {
    return (
      <>
        <Toolbar title="Indexes" />
        <div className="card">
          <div className="card-body" style={{ padding: "44px 16px", textAlign: "center" }}>
            <div className="kpi-label" style={{ color: "var(--quiet)" }}>Index registry not active yet</div>
            <p style={{ fontSize: 13, color: "var(--muted)", maxWidth: 520, margin: "10px auto 0", lineHeight: 1.6 }}>
              Apply the <span className="mono">2026-06-15_indexes</span> migration on the store (Supabase SQL editor)
              to enable the index registry. Until then nothing is fabricated — this surface stays honestly empty.
            </p>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Toolbar title="Indexes" />
      <IndexesTable indexes={indexes.indexes} />
    </>
  );
}
