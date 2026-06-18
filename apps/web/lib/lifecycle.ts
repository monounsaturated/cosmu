// module: the SINGLE web source of truth for the strategy lifecycle taxonomy. Two surfaces describe the same
// pipeline with different vocabulary — the screener's `LifeStatus` (the normalized engine-status → 5 lanes,
// where "lab" reads as "New" — authored, ready, not-yet-computed — and "screened" as Backtest) and the
// strat-sheet's `Stage` (the already-derived display stage). They render IDENTICALLY (same labels, same badge
// classes); this module holds both unions, the LifeStatus→Stage bridge, and the shared label + badge-class maps
// so the two never drift. Mirrors the engine's lifecycle vocabulary (cosmu/knowledge/lifecycle_status.py:
// SCREENER_LABEL) on the web side — keep the two in lockstep.
//
// NOTE: status is BADGE-ONLY for the money path (the live/arming interlock reads forward evidence, not this).
// "draft" (still being authored) is an engine-side authoring sub-state UPSTREAM of "lab"; the screener surfaces
// authored-but-uncomputed versions in the "lab"/"New" lane (no separate web lane needed until drafts are stored).

// The screener's normalized lifecycle lane. "lab" → New, "screened" → Backtest.
export type LifeStatus = "lab" | "screened" | "paper" | "live" | "killed";
// The strat-sheet's derived display stage (the LifeStatus lanes spelled with their public stage names).
export type Stage = "queued" | "backtest" | "paper" | "live" | "killed";

// Map the screener's lifecycle lane onto the sheet's Stage union so the sheet badge matches the table badge.
export const LIFE_TO_STAGE: Record<LifeStatus, Stage> = {
  lab: "queued",
  screened: "backtest",
  paper: "paper",
  live: "live",
  killed: "killed"
};

// Public stage labels — keyed by LifeStatus lane (screener) and by Stage name (sheet); same rendered text.
// The "lab"/"queued" lane reads "New" (authored, ready, not-yet-computed) — was "Queued".
export const LIFE_LABEL: Record<LifeStatus, string> = {
  lab: "New",
  screened: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};
export const STAGE_LABEL: Record<Stage, string> = {
  queued: "New",
  backtest: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};

// ── Strategy MODEL kind (strategy_versions.kind, off the generated LeaderboardRow.kind / StrategyDetailResponse.kind).
// ORTHOGONAL to the lifecycle Stage above and to provenance/strategy_kind: this is HOW the strategy is modelled —
// "quant" = a typed StrategySpec routed through deterministic Gate A (every strategy today), "llm" = an agentic/NL
// AgentSpec. Subtle by design (all rows are 'quant' now); reuses the existing `.badge` color classes. ──
export type Kind = "quant" | "llm";
export const KIND_LABEL: Record<Kind, string> = {
  quant: "Quant",
  llm: "LLM"
};
// Reuse the shared badge palette: muted for the quant default (subtle), iris to flag an LLM/agentic strategy.
export const KIND_BADGE_CLASS: Record<Kind, string> = {
  quant: "badge badge-muted",
  llm: "badge badge-iris"
};

// The Iris Bento `.stage-badge` class set — same classes from either vocabulary.
export const LIFE_BADGE_CLASS: Record<LifeStatus, string> = {
  lab: "stage-badge sb-queued",
  screened: "stage-badge sb-backtest-stage",
  paper: "stage-badge sb-paper",
  live: "stage-badge sb-live",
  killed: "stage-badge sb-killed"
};
export const STAGE_BADGE_CLASS: Record<Stage, string> = {
  queued: "stage-badge sb-queued",
  backtest: "stage-badge sb-backtest-stage",
  paper: "stage-badge sb-paper",
  live: "stage-badge sb-live",
  killed: "stage-badge sb-killed"
};
