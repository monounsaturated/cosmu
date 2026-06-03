// module: Live trading contracts. RESPONSE shapes come from the generated @cosmu/contracts-ts
// (Pydantic -> OpenAPI -> TS; never hand-typed). Only the request BODIES + LiveMode are local —
// OpenAPI doesn't emit named request-body types, and the engine owns the verdict either way.
//
//   POST /toggle/live   body {enabled, confirm}        -> ToggleLiveResponse (= generated ToggleResponse)
//   POST /live/activate body {per_strategy_cap, global_cap, max_daily_loss, confirm} -> ActivateResponse
//   POST /live/defund   body {scope, version_id?}      -> DefundResponse
//   GET  /live/positions                               -> PositionsResponse (= generated LivePositionsResponse)
//
// NON-NEGOTIABLE SAFETY: a real order is submitted ONLY when ALL hold — live toggle ON +
// execution keys present + gate PASSED + caps available + not kill-switched. Otherwise the
// engine paper-simulates. The web never decides this; it only surfaces the engine's verdict.

import type {
  ActivateResponse,
  DefundResponse,
  EligibleStrategy,
  LiveCaps,
  LivePosition,
  LivePositionsResponse,
  ToggleResponse,
} from "@cosmu/contracts-ts";

// Generated response/shared types, re-exported under the names the surface uses.
export type { ActivateResponse, DefundResponse, EligibleStrategy, LivePosition };
export type Caps = LiveCaps;
export type PositionsResponse = LivePositionsResponse;
export type ToggleLiveResponse = ToggleResponse;

// Request bodies + the mode union are local (not emitted by OpenAPI).
export type LiveMode = "testnet" | "live" | "sim";

export interface ToggleLiveBody {
  enabled: boolean;
  confirm: boolean;
}

export interface ActivateBody {
  per_strategy_cap: number;
  global_cap: number;
  max_daily_loss: number;
  confirm: boolean;
}

export interface DefundBody {
  scope: "all" | "strategy";
  version_id?: string;
}
