// module: /live route. The gated trading surface — server-fetches the real positions snapshot
// (off by default, paper/testnet unless explicitly armed) and hands it to the client surface
// which owns the 2-click activation flow, defund controls, and offline demo fallback.

import { getLivePositions } from "../data";
import { LiveSurface } from "@/components/live/live-surface";

export default async function LivePage() {
  const initial = await getLivePositions();
  return <LiveSurface initial={initial} />;
}
