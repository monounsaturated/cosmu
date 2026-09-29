// module: provenance / strategy-kind / lane derivation for the Strategies surface. ALL pure, DETERMINISTIC,
// and derived from REAL contract fields — never a hand-applied tag, so the badges can never drift from the
// strategy's actual inputs and routing.
//
//   • provenance  — WHO/WHAT authored the edge, bucketed for the operator into Quant / Vibe / Astro. Read off
//     the version `origin` (seed/finder/mutation/… = the autonomous quant lab; chat/nlp/inbox/dump = a
//     natural-language "vibe" idea) PLUS the referenced features (any astro_* feature ⇒ Astro, the non-causal
//     control family). Honest "Quant" default — the research lab is the source of everything not otherwise tagged.
//   • strategy_kind — the spec's first-class TYPE discriminator (indicator / event / regime). Off the spec; an
//     `edge_type === "event"` row is a best-effort proxy when only the leaderboard row is in hand.
//   • lane — the spec's evaluation lane: "gate" (novel in-sample-mined, judged by the 0.95 deflated-Sharpe +
//     BH-FDR Gate) vs "deploy" (externally-documented, judged by the positive-OOS deployment bar). We surface
//     a third READ-ONLY label "explore" for the watch-list/rejects disposition when the spec marks it — never a
//     money lane, purely how the operator should read the row.

export type Provenance = "quant" | "vibe" | "astro";
export type StrategyKind = "indicator" | "event" | "regime";
export type EvalLane = "gate" | "deploy" | "explore";

// Origins minted by the natural-language / "vibe" intake path (chat idea → typed spec). Everything not in this
// set (seed, finder, mutation, wildcard, pine, template, documented, …) is the autonomous Quant lab.
const VIBE_ORIGINS = new Set(["chat", "nlp", "nl", "vibe", "inbox", "dump", "idea"]);

export type ProvenanceInfo = { key: Provenance; label: string; badgeClass: string; tip: string };

const PROVENANCE_INFO: Record<Provenance, ProvenanceInfo> = {
  quant: {
    key: "quant",
    label: "Quant",
    badgeClass: "badge badge-iris",
    tip: "Mined by the autonomous quant lab (seed / finder / mutation / documented) and judged by the deterministic Gate."
  },
  vibe: {
    key: "vibe",
    label: "Vibe",
    badgeClass: "badge badge-gold",
    tip: "Authored from a natural-language idea (chat / inbox). Same Gate, but it entered as a human-described hypothesis, not a sweep."
  },
  astro: {
    key: "astro",
    label: "Astro",
    badgeClass: "badge badge-muted",
    tip: "References an astro (lunar/planetary ephemeris) feature — a NON-CAUSAL control family. Surfaced for transparency; never expected to clear the Gate."
  }
};

// Any astro feature flips the row to the Astro bucket (it's the most informative provenance), else the origin
// decides Vibe vs Quant. `features` are the spec's referenced feature names already carried on the row.
export function provenanceOf(origin: string | null | undefined, features: readonly string[] | null | undefined): ProvenanceInfo {
  if (Array.isArray(features) && features.some((f) => typeof f === "string" && f.toLowerCase().startsWith("astro"))) {
    return PROVENANCE_INFO.astro;
  }
  const o = (origin ?? "").trim().toLowerCase();
  if (VIBE_ORIGINS.has(o)) return PROVENANCE_INFO.vibe;
  return PROVENANCE_INFO.quant;
}

export type KindInfo = { key: StrategyKind; label: string; badgeClass: string; tip: string };

const KIND_INFO: Record<StrategyKind, KindInfo> = {
  indicator: {
    key: "indicator",
    label: "Indicator",
    badgeClass: "badge badge-muted",
    tip: "Classic price/TA + alt-condition strategy: entries fire when indicator conditions line up."
  },
  event: {
    key: "event",
    label: "Event",
    badgeClass: "badge badge-iris",
    tip: "Entries fire on a typed point-in-time market EVENT (news / catalyst), not a rolling indicator condition."
  },
  regime: {
    key: "regime",
    label: "Regime",
    badgeClass: "badge badge-gold",
    tip: "A slow-tilt overlay that shifts exposure with the prevailing market regime rather than firing discrete entries."
  }
};

const KINDS: ReadonlySet<string> = new Set<StrategyKind>(["indicator", "event", "regime"]);

// Authoritative kind off the spec's `strategy_kind` discriminator; falls back to "indicator" (the spec default).
export function strategyKindOf(spec: Record<string, unknown> | null | undefined): KindInfo {
  const k = spec && typeof spec.strategy_kind === "string" ? spec.strategy_kind.toLowerCase() : "indicator";
  return KIND_INFO[(KINDS.has(k) ? k : "indicator") as StrategyKind];
}

export type LaneInfo = { key: EvalLane; label: string; badgeClass: string; tip: string };

const LANE_INFO: Record<EvalLane, LaneInfo> = {
  gate: {
    key: "gate",
    label: "Gate",
    badgeClass: "badge badge-up",
    tip: "Novel in-sample-mined hypothesis — judged by the honest 0.95 deflated-Sharpe bar + BH-FDR cohort Gate."
  },
  deploy: {
    key: "deploy",
    label: "Deploy",
    badgeClass: "badge badge-iris",
    tip: "Externally-documented strategy with long OOS/live evidence — judged by the positive-OOS deployment bar, not the in-sample Gate."
  },
  explore: {
    key: "explore",
    label: "Explore",
    badgeClass: "badge badge-muted",
    tip: "Watch-list / rejects disposition — tracked at zero capital to measure Type-II error. Never on the money path."
  }
};

const LANES: ReadonlySet<string> = new Set<EvalLane>(["gate", "deploy", "explore"]);

// Authoritative lane off the spec's `lane` discriminator; falls back to "gate" (the spec default).
export function laneOf(spec: Record<string, unknown> | null | undefined): LaneInfo {
  const l = spec && typeof spec.lane === "string" ? spec.lane.toLowerCase() : "gate";
  return LANE_INFO[(LANES.has(l) ? l : "gate") as EvalLane];
}
