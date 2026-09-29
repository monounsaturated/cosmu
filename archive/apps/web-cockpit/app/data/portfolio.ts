// module: the CANONICAL home for the live-portfolio read-outs the v18 Live + Strategies surfaces bind to.
//
//   getPortfolioSummary() — GET /portfolio/summary — the live-vs-sim MONEY SPLIT. The one read-out that
//     must NEVER label SIM capital as live: when nothing is routed live (`has_live` false) every `live_*`
//     money field is null and the UI renders an explicit "—", never 0 and never the SIM number.
//   getRules()            — GET /live/rules — the live-trading Rules the operator edits in the Rules modal:
//     the hard global $ blocker (`global_max_notional`), the daily-loss cap, the per-strategy cap, and the
//     PER-VENUE notional caps with each legal venue's real `deployed_usd` + headroom (`available_usd`).
//
// Both fetchers physically live in their domain modules (overview.ts / live.ts) alongside their siblings;
// this module re-exports them under one canonical import path so surfaces can pull the live MONEY SPLIT +
// Rules WITHOUT the barrel ambiguity (the `@/app/data` barrel re-exports many domains). Importing from
// `@/app/data/portfolio` is unambiguous and self-documenting. No new fetch logic lives here.

export { getPortfolioSummary } from "./overview";
export { getRules } from "./live";
export type { PortfolioSummaryResponse, RulesResponse, VenueRule, RulesRequest, VenueRuleSet } from "@cosmu/contracts-ts";
