// module: /live route. The gated trading surface — server-fetches the real positions snapshot, the
// live-vs-sim money split (getPortfolioSummary), the live equity curve (getOverview), and the editable
// hard-limit Rules (getRules) — then hands them to the client surface which owns the 2-click activation
// flow, the Rules modal, defund controls, and an honest not-connected / "—" state. Live is OFF by
// default and the surface NEVER labels SIM capital as live: when nothing is routed live, every live
// money figure renders an explicit "—" (the engine returns null), never 0 and never the SIM number.

import { getLivePositions, getLiveVenues, getPortfolioSummary, getRules, getOverview } from "../data";
import { LiveSurface } from "@/components/live/live-surface";
import { StrategyStages } from "@/components/nav/strategy-stages";

export default async function LivePage() {
  const [initial, venues, summary, rules, overview] = await Promise.all([
    getLivePositions(),
    getLiveVenues(),
    getPortfolioSummary(),
    getRules(),
    getOverview()
  ]);
  return (
    // ONE max-width column + ONE responsive padding rhythm matching every other page
    // (px-4 py-6 sm:px-5 sm:py-7 lg:px-7). The stage strip and the surface share that column so the
    // Live page no longer has the double-wrapper top-padding gap the operator flagged.
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      {/* Live is the final lifecycle stage — keep the stage-filter strip in reach (it moved off the top nav). */}
      <StrategyStages />
      <LiveSurface
        initial={initial}
        initialVenues={venues}
        initialSummary={{ ...summary.summary, connected: summary.connected }}
        initialRules={{ ...rules.rules, connected: rules.connected }}
        equityCurve={overview.overview.equity_curve}
      />
    </div>
  );
}
