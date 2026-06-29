// Conviction — the propose-only LLM/Conviction review queue (cosmu/conviction). When a followed account whose
// AUTHORITY clears the threshold posts a fresh, actionable asset-call, the engine sizes a capped conviction bet
// (authority × EV, hard max-loss) and queues it here, off GET /conviction/proposals, for a HUMAN to review + arm.
// Lean + overview-led: a one-line summary, then the proposal cards with their authority evidence.
//
// HONESTY + SAFETY: not-connected → the engine-not-connected state; an empty queue → the honest "nothing
// proposed yet" state (never a fabricated bet). PROPOSE-ONLY — this surface shows proposals and evidence; it has
// no arm button and moves no money. Arming is a separate, explicit human action; the conviction lane never
// auto-arms (guardrails + small size + human-armed, NOT the deterministic quant Gate).

import { Suspense } from "react";
import { engineConfigured, getConvictionProposals } from "../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected } from "@/components/ui/honest-state";
import { ConvictionProposals } from "@/components/conviction/proposals-table";

export const dynamic = "force-dynamic";

export default function ConvictionPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Conviction" />
            <div className="skel" style={{ height: 360 }} />
          </>
        }
      >
        <ConvictionData />
      </Suspense>
    </Page>
  );
}

async function ConvictionData() {
  const { conviction, connected } = await getConvictionProposals();

  if (!connected) {
    return (
      <>
        <Toolbar title="Conviction" />
        <NotConnected
          configured={engineConfigured}
          what="The conviction queue is propose-only trade ideas built from high-authority accounts' fresh asset-calls — sized by authority × EV under a hard max-loss cap, for a human to review and arm. It appears here once the engine is connected — no demo bets."
        />
      </>
    );
  }

  return (
    <>
      <Toolbar title="Conviction" />
      <ConvictionProposals conviction={conviction} />
    </>
  );
}
