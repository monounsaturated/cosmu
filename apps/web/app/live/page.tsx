// module: /live route. The gated trading surface — server-fetches the real positions snapshot
// (off by default, paper/testnet unless explicitly armed) and hands it to the client surface
// which owns the 2-click activation flow, defund controls, and an honest not-connected state.

import { getLivePositions, getLiveVenues } from "../data";
import { LiveSurface } from "@/components/live/live-surface";
import { StrategyStages } from "@/components/nav/strategy-stages";

export default async function LivePage() {
  const [initial, venues] = await Promise.all([getLivePositions(), getLiveVenues()]);
  return (
    <>
      {/* Live is the final lifecycle stage — keep the stage-filter strip in reach (it moved off the top nav). */}
      <div className="mx-auto max-w-[1100px] px-5 pt-7 lg:px-7">
        <StrategyStages />
      </div>
      <LiveSurface initial={initial} initialVenues={venues} />
    </>
  );
}
