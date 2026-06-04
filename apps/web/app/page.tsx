// module: the Overview — Cosmu's cockpit. A SERVER component: it fetches every engine surface once,
// packs the results into a plain CockpitData snapshot, and hands it to the client <Cockpit/> shell, which
// renders the operator's chosen widgets (modular, pick-what-to-display, persisted). The cockpit leads with
// TOOL-ALIGNED metrics (gate funnel, net-of-fee edge, data freshness) rather than $-denominated vanity
// numbers — there is no real money by default. HONEST: when the engine is unreachable we render a single
// "not connected" state and never a fabricated cockpit.

import {
  engineConfigured,
  getAutonomyStatus,
  getEvents,
  getInboxQueue,
  getIntelligence,
  getLeaderboard,
  getLivePositions,
  getMind,
  getOverview,
  getPopulation,
  getRecommendations
} from "./data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { NotConnected } from "@/components/ui/honest-state";
import { Cockpit } from "@/components/cockpit/cockpit";
import type { CockpitData } from "@/components/cockpit/cockpit-data";

export default async function OverviewPage() {
  const [
    { overview, connected },
    { leaderboard },
    { items: recommendations, connected: recConnected },
    { events },
    { status: autonomy, connected: autonomyConnected },
    { intelligence, connected: intelConnected },
    { population },
    { mind },
    { items: queuedIdeas, connected: inboxConnected },
    positions
  ] = await Promise.all([
    getOverview(),
    getLeaderboard(),
    getRecommendations(),
    getEvents(),
    getAutonomyStatus(),
    getIntelligence(),
    getPopulation(),
    getMind(),
    getInboxQueue(),
    getLivePositions()
  ]);

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">cockpit</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">Mission control</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="The cockpit shows the machine's real edge — the gate funnel, net-of-fee survivors, and data freshness. Connect the engine to see live numbers."
        />
      </div>
    );
  }

  const data: CockpitData = {
    configured: engineConfigured,
    connected,
    overview,
    leaderboard: leaderboard.rows as LeaderboardRow[],
    population,
    mind,
    intelligence,
    events,
    recommendations,
    recConnected,
    autonomy,
    autonomyConnected,
    intelConnected,
    queuedIdeas,
    inboxConnected,
    positions
  };

  return <Cockpit data={data} />;
}
