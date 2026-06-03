// module: Live trading contracts. RESPONSE shapes come from the generated @cosmu/contracts-ts
// (Pydantic -> OpenAPI -> TS; never hand-typed). Only the request BODIES + LiveMode are local —
// OpenAPI doesn't emit named request-body types, and the engine owns the verdict either way.
//
//   POST /toggle/live          body {enabled, confirm}                -> ToggleLiveResponse
//   POST /live/activate        body {per_strategy_cap, ...confirm}    -> ActivateResponse
//   POST /live/launch          body {version_id, venue_id, ...}       -> LaunchActivateResponse
//   POST /live/defund          body {scope, version_id?}              -> DefundResponse
//   GET  /live/positions                                              -> PositionsResponse
//   GET  /live/venue-catalog                                          -> VenueCatalogResponse
//
// NON-NEGOTIABLE SAFETY: a real order is submitted ONLY when ALL hold — live toggle ON +
// execution keys present + gate PASSED + caps available + not kill-switched. Otherwise the
// engine paper-simulates. The web never decides this; it only surfaces the engine's verdict.

import type {
  ActivateResponse,
  DefundResponse,
  EligibleStrategy,
  LaunchActivateResponse,
  LiveCaps,
  LivePosition,
  LivePositionsResponse,
  ToggleResponse,
  VenueCatalogResponse,
  VenueFeeInfo,
  VenueFeeTierInfo,
  VenueInstrumentInfo,
} from "@cosmu/contracts-ts";

// Generated response/shared types, re-exported under the names the surface uses.
export type {
  ActivateResponse,
  DefundResponse,
  EligibleStrategy,
  LaunchActivateResponse,
  LivePosition,
  VenueCatalogResponse,
  VenueFeeInfo,
  VenueFeeTierInfo,
  VenueInstrumentInfo,
};
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

export interface LaunchBody {
  version_id: string;
  venue_id: string;
  symbol: string;
  budget: number;
  per_strategy_cap: number;
  global_cap: number;
  max_daily_loss: number;
  confirm: boolean;
}

export interface DefundBody {
  scope: "all" | "strategy";
  version_id?: string;
}

// GET /live/venues — the honest per-venue live picture. Mirrors the engine's LiveVenue/LiveVenuesResponse
// (Pydantic). Kept local for now, like the request bodies above + the cross-asset-gate precedent.
export interface LiveVenue {
  id: string;
  name: string;
  kind: "crypto" | "equity" | "prediction";
  live_legal: boolean;   // legal to move real money from our jurisdiction
  connected: boolean;    // execution keys wired (else "not connected")
  enabled: boolean;      // ticked into the trading universe
  deployed_usd: number;  // real capital at risk here now
}

export interface LiveVenuesResponse {
  jurisdiction: string;
  global_cap: number;          // total live budget across venues
  total_deployed_usd: number;
  venues: LiveVenue[];
}
