// module: autonomy command-center contracts. The shared engine<->web contract for the autonomous
// machine the human OVERSEES. snake_case to mirror the engine exactly.
//
// DELIBERATE LOCAL MIRROR — not re-exported from @cosmu/contracts-ts because the generated types
// use different names (AutonomyStatusResponse, TickSummary, AutonomyTickResponse,
// AutonomyPauseResponse, RecommendationActionResponse) that would require renaming every call-site.
// When the generator is updated to emit these exact names, delete this file and re-point consumers.
// Until then, keep this file in sync manually with the engine's /autonomy routes.
//
// PRINCIPLE: nothing here decides money. The deterministic scorer/Gate disposes (out of any LLM
// path) and alone decides survival + funding. The autonomy loop only PROPOSES; the human arms live.
// Every call is LLM-OPTIONAL + OFFLINE-testable: with no engine the client returns an honest
// not-connected state and never fabricates a status or a result.
//
//   GET  /autonomy/status -> AutonomyStatus
//   POST /autonomy/pause  -> { paused: true }
//   POST /autonomy/resume -> { paused: false }
//   POST /autonomy/tick   -> AutonomyTickResult (one bounded cycle)
//   POST /recommendations/{id}/approve  -> { ok, applied, reason? }
//   POST /recommendations/{id}/dismiss  -> { ok }

// What the machine did last cycle and what it produced. All counts, never money.
export interface AutonomySummary {
  authored: number;
  gated_passed: number;
  funded: number;
  recommendations: number;
}

export interface AutonomyStatus {
  running: boolean;
  paused: boolean;
  live_enabled: boolean;
  cycles_run: number;
  last_tick_at: string | null;
  last_action: string;
  next_action: string;
  last_summary: AutonomySummary;
}

// POST /autonomy/tick — one bounded cycle's result.
export type AutonomyTickResult = AutonomySummary;

export interface PauseResumeResult {
  paused: boolean;
}

export interface ApproveResult {
  ok: boolean;
  applied: boolean;
  reason?: string;
}

export interface DismissResult {
  ok: boolean;
}

// Structurally-empty, honest default. running:false + paused:false + a plain "not started yet"
// reads correctly as "no machine activity to show", never as a fabricated running state.
export const EMPTY_AUTONOMY_STATUS: AutonomyStatus = {
  running: false,
  paused: false,
  live_enabled: false,
  cycles_run: 0,
  last_tick_at: null,
  last_action: "",
  next_action: "",
  last_summary: { authored: 0, gated_passed: 0, funded: 0, recommendations: 0 }
};
