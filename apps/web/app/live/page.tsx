// module: /live route. The gated trading surface — server-fetches the real positions snapshot
// (off by default, paper/testnet unless explicitly armed) and hands it to the client surface
// which owns the 2-click activation flow, defund controls, and an honest not-connected state.

import { getLivePositions, getLiveVenues } from "../data";
import { LiveSurface } from "@/components/live/live-surface";

export default async function LivePage() {
  const [initial, venues] = await Promise.all([getLivePositions(), getLiveVenues()]);
  return <LiveSurface initial={initial} initialVenues={venues} />;
}
