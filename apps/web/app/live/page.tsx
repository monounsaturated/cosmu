// /live — the gated, money screen (Iris Bento). Server-fetches the real positions snapshot, the live-vs-sim
// money split (getPortfolioSummary), the live equity curve (getOverview), and the editable hard-limit Rules
// (getRules), then hands them to the client surface which owns the toolbar (ARM state + Rules + Stop), the
// 2-click activation flow, the Rules / liquidate modals, and an honest not-connected / "—" state.
//
// Live is OFF by default and the surface NEVER labels SIM capital as live: when nothing is routed live, every
// live money figure renders an explicit "—" (the engine returns null), never 0 and never the SIM number.
//
// Loading UX: the LiveSurface owns its toolbar (the controls are client + data-coupled), so the instant
// chrome is a lightweight toolbar skeleton; the real toolbar + dashboard stream in once the data resolves.

import { Suspense } from "react";
import { getLivePositions, getPortfolioSummary, getRules, getOverview } from "../data";
import { LiveSurface } from "@/components/live/live-surface";
import { Page, Toolbar } from "@/components/ui/toolbar";

export default function LivePage() {
  return (
    <Suspense
      fallback={
        <Page>
          <Toolbar title="Live" />
          <div className="skel" style={{ height: 420 }} />
        </Page>
      }
    >
      <LiveData />
    </Suspense>
  );
}

async function LiveData() {
  const [initial, summary, rules, overview] = await Promise.all([
    getLivePositions(),
    getPortfolioSummary(),
    getRules(),
    getOverview()
  ]);
  return (
    <LiveSurface
      initial={initial}
      initialSummary={{ ...summary.summary, connected: summary.connected }}
      initialRules={{ ...rules.rules, connected: rules.connected }}
      equityCurve={overview.overview.equity_curve}
    />
  );
}
