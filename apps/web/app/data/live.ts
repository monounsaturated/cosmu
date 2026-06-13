import type { AutonomyStatusResponse, RulesResponse } from "@cosmu/contracts-ts";
import type { PositionsResponse, LiveVenuesResponse } from "@/components/live/contracts";
import { getJson } from "./client";

// Structurally-empty, honest default. running:false + paused:false reads correctly as "no machine
// activity to show", never as a fabricated running state.
const emptyAutonomyStatus: AutonomyStatusResponse = {
  running: false,
  paused: false,
  live_enabled: false,
  cycles_run: 0,
  last_tick_at: null,
  last_action: "",
  next_action: "",
  last_summary: { authored: 0, gated_passed: 0, funded: 0, recommendations: 0 }
};

const emptyPositions: PositionsResponse = {
  armed: false,
  mode: "sim",
  daily_loss: 0,
  caps: { per_strategy_cap: 0, global_cap: 0, max_daily_loss: 0 },
  positions: []
};

const emptyVenues: LiveVenuesResponse = { jurisdiction: "", global_cap: 0, total_deployed_usd: 0, venues: [] };

// GET /autonomy/status — the command-center status of the autonomous machine the human oversees:
// running/paused, live on/off, cycles run, what it last did + will do next, and the last cycle's
// counts. `connected:false` renders an honest "machine status unknown" state — never a fake running
// machine. The deterministic Gate/scorer still disposes; this status only reports, never decides.
export async function getAutonomyStatus(): Promise<{ status: AutonomyStatusResponse; connected: boolean }> {
  const { data, connected } = await getJson("/autonomy/status", emptyAutonomyStatus);
  return { status: data, connected };
}

// Live trading positions snapshot for the /live surface. `connected:false` is shown as engine-
// offline — never presented as armed or live.
export async function getLivePositions(): Promise<PositionsResponse & { connected: boolean }> {
  const { data, connected } = await getJson<PositionsResponse>("/live/positions", emptyPositions);
  return { ...data, connected };
}

export async function getLiveVenues(): Promise<LiveVenuesResponse & { connected: boolean }> {
  const { data, connected } = await getJson<LiveVenuesResponse>("/live/venues", emptyVenues);
  return { ...data, connected };
}

// GET /live/rules — the live-trading Rules (hard global $ blocker + daily-loss + per-venue caps + each
// venue's real deployed/headroom). `connected:false` → honest zero/empty, never a fabricated cap.
const emptyRules: RulesResponse = { global_max_notional: 0, max_daily_loss: 0, per_strategy_cap: 0, venues: [] };

export async function getRules(): Promise<{ rules: RulesResponse; connected: boolean }> {
  const { data, connected } = await getJson<RulesResponse>("/live/rules", emptyRules);
  return { rules: data, connected };
}
