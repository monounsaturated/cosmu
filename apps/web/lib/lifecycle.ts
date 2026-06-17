// module: the SINGLE web source of truth for the strategy lifecycle taxonomy. Two surfaces describe the same
// pipeline with different vocabulary — the screener's `LifeStatus` (the normalized engine-status → 5 lanes,
// where "lab" reads as Queued and "screened" as Backtest) and the strat-sheet's `Stage` (the
// already-derived display stage). They render IDENTICALLY (same labels, same badge classes); this module
// holds both unions, the LifeStatus→Stage bridge, and the shared label + badge-class maps so the two never
// drift. Mirrors the engine's lifecycle vocabulary (cosmu/knowledge/lifecycle_status.py) on the web side.
//
// NOTE: status is BADGE-ONLY for the money path (the live/arming interlock reads forward evidence, not this).

// The screener's normalized lifecycle lane. "lab" → Queued, "screened" → Backtest.
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
export const LIFE_LABEL: Record<LifeStatus, string> = {
  lab: "Queued",
  screened: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};
export const STAGE_LABEL: Record<Stage, string> = {
  queued: "Queued",
  backtest: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
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
