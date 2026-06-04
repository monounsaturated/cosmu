// module: the cockpit's serializable data snapshot. The Overview page is a SERVER component that fetches
// every engine surface once, packs it into this plain object, and hands it to the client <Cockpit/> shell
// (which renders the operator's chosen widgets). Everything here is plain JSON so it crosses the server →
// client boundary cleanly. Honesty is preserved: per-surface `connected` flags travel with the data so a
// widget can render its own honest "not connected / nothing yet" state — never a fabricated number.

import type {
  Event,
  LeaderboardRow,
  MindResponse,
  OverviewResponse,
  PopulationResponse,
  Recommendation
} from "@cosmu/contracts-ts";
import type { InboxQueueItem, IntelligenceResponse } from "@/app/data";
import type { PositionsResponse } from "@/components/live/contracts";
import type { AutonomyStatus } from "@/app/autonomy-contracts";

export interface CockpitData {
  configured: boolean;
  connected: boolean;
  overview: OverviewResponse;
  leaderboard: LeaderboardRow[];
  population: PopulationResponse;
  mind: MindResponse;
  intelligence: IntelligenceResponse;
  events: Event[];
  recommendations: Recommendation[];
  recConnected: boolean;
  autonomy: AutonomyStatus;
  autonomyConnected: boolean;
  intelConnected: boolean;
  queuedIdeas: InboxQueueItem[];
  inboxConnected: boolean;
  positions: PositionsResponse;
}
