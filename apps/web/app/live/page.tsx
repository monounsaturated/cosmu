// module: /live route. The gated trading surface — server-fetches the real positions snapshot
// (off by default, paper/testnet unless explicitly armed) and hands it to the client surface
// which owns the 2-click activation flow, defund controls, and an honest not-connected state.

import { getLivePositions, getLiveVenues } from "../data";
import { LiveSurface } from "@/components/live/live-surface";
import { StrategyStages } from "@/components/nav/strategy-stages";

export default async function LivePage() {
  const [initial, venues] = await Promise.all([getLivePositions(), getLiveVenues()]);
  return (
    // ONE max-width column + ONE responsive padding rhythm matching every other page
    // (px-4 py-6 sm:px-5 sm:py-7 lg:px-7). The stage strip and the surface share that column so the
    // Live page no longer has the double-wrapper top-padding gap the operator flagged.
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      {/* Live is the final lifecycle stage — keep the stage-filter strip in reach (it moved off the top nav). */}
      <StrategyStages />
      <LiveSurface initial={initial} initialVenues={venues} />
    </div>
  );
}
