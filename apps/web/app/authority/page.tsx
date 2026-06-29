// Authority — the proprietary-data dashboard: which accounts to trust, scored on whether their past asset calls
// corroborated the later tape. One composite row per account (Brier · hit-rate · EV/payoff · magnitude ·
// lead-time · consistency · composite · top-3 movers), straight off GET /authority. Lean + overview-led: a
// sortable table, no heavy viz. This only SCORES — a high score later powers a separate LLM strategy that obeys
// its signals (out of scope here); it never funds or fires.
//
// HONESTY: not-connected → the engine-not-connected state; an empty store → the honest "no accounts scored yet"
// state (never a fabricated row). Every score is a real field the engine computed from resolved calls.

import { Suspense } from "react";
import { engineConfigured, getAuthority } from "../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected } from "@/components/ui/honest-state";
import { AuthorityTable } from "@/components/authority/authority-table";

export const dynamic = "force-dynamic";

export default function AuthorityPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Authority" />
            <div className="skel" style={{ height: 360 }} />
          </>
        }
      >
        <AuthorityData />
      </Suspense>
    </Page>
  );
}

async function AuthorityData() {
  const { authority, connected } = await getAuthority();

  if (!connected) {
    return (
      <>
        <Toolbar title="Authority" />
        <NotConnected
          configured={engineConfigured}
          what="The Authority scoreboard ranks accounts by whether their past asset calls corroborated the tape — calibration, hit-rate, and PAYOFF (profit weighted highest). It is proprietary data, curated locally; it appears here once the engine is connected — no demo rows."
        />
      </>
    );
  }

  return (
    <>
      <Toolbar title="Authority" />
      <AuthorityTable authority={authority} />
    </>
  );
}
