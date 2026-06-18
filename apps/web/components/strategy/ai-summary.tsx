import type { Stage } from "./stage-control";
import { fmtTz } from "@/lib/utils";

// module: AiSummary — the v18 strat-sheet summary block (Iris Bento `.psec.ai-sec`). ALWAYS the SAME two-part
// structure, two paragraphs:
//   1. "What this does" — plain-language read of the strategy. HONEST BY CONSTRUCTION: text comes ONLY from a
//      real recorded field — the operator-agent summary (research_notes kind='summary', served as summary_md),
//      else the strategy's own recorded spec rationale. Nothing generated here; a "stale" pill shows when the
//      recorded summary's facts moved. An agent (Claude Code) writes + periodically refreshes this part.
//   2. "Why it's <Stage>" — why the strategy sits where it does in the lifecycle. DETERMINISTIC: derived live
//      from the real stage + the headline backtest's Gate verdict (deflated-Sharpe, PBO, OOS, max-DD). Not an
//      LLM guess, so it can NEVER go stale or fabricate — it always tells the current truth.
//
// Advisory only — never the Gate. This narrates; the deterministic Gate alone funds or kills.

// The real Gate facts from the headline backtest — the numbers behind "why this stage". Null when none ran.
export type GateFacts = {
  passedGates: boolean;
  // The deflated-Sharpe RATIO (ranking number, can exceed 1.0) — kept for reference, but NOT what the 0.95 bar
  // checks, so the prose never cites it as the gated number (that was the "0.98 — below the 0.95 bar" contradiction).
  deflatedSharpe: number;
  // The GATED metric: deflated-Sharpe PROBABILITY in [0,1] — the value the strict 0.95 bar actually checks. null
  // when the engine could not recompute it (pre-migration / arm rows); the prose then states the bar without a number.
  deflatedSharpeProb: number | null;
  pbo: number;
  oosReturn: number; // fraction: 0.94 = +94%
  oosWindowDays?: number | null;
  maxDd: number; // fraction: 0.083 = 8.3%
} | null;

// Lane labels mirror lib/lifecycle.ts (the "queued" lane reads "New" — authored, ready, not-yet-computed).
const STAGE_LABEL: Record<Stage, string> = {
  queued: "New",
  backtest: "Backtest",
  paper: "Paper",
  live: "Live",
  killed: "Killed"
};

const pct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const absPct = (x: number) => `${(Math.abs(x) * 100).toFixed(1)}%`;
function fmtWindow(days?: number | null): string {
  if (!days || days <= 0) return "the test window";
  const yr = days / 365;
  return yr >= 1 ? `~${yr.toFixed(1)}yr` : `~${Math.round(days)}d`;
}

// The deflated-Sharpe PROBABILITY clause — the number the strict 0.95 bar actually checks. Falls back to a
// numberless phrase when the engine couldn't recompute the probability, so the prose is never contradictory
// (it used to cite the deflated-Sharpe RATIO, e.g. 0.98, against the 0.95 PROBABILITY bar — "0.98 below 0.95").
function dsrProbClause(g: NonNullable<GateFacts>): string {
  return g.deflatedSharpeProb !== null
    ? `deflated-Sharpe probability ${g.deflatedSharpeProb.toFixed(2)}`
    : "deflated-Sharpe probability";
}

// DETERMINISTIC plain-language "why this stage", grounded ONLY in the real stage + Gate facts. Always current
// (computed on render), never fabricated, never stale. Same shape for every strategy.
export function stageReason(stage: Stage, g: GateFacts): string {
  switch (stage) {
    case "queued":
      return "It's authored and waiting in the queue — no backtest has run yet, so the Gate hasn't judged it. It moves to Backtest automatically on the next research tick.";
    case "backtest":
      if (g && g.passedGates) {
        return `It cleared the Gate in backtest (${dsrProbClause(g)} ≥ 0.95, PBO ${g.pbo.toFixed(2)}, OOS ${pct(g.oosReturn)} over ${fmtWindow(g.oosWindowDays)}) but hasn't been funded a paper track yet. The Gate promotes survivors — you don't move them by hand.`;
      }
      return `It's screening in Backtest and has NOT cleared the Gate${g ? ` (${dsrProbClause(g)} — below the strict 0.95 bar, max drawdown ${absPct(g.maxDd)})` : ""}. That's the machine working as designed: the Gate is deliberately strict, so most ideas are honestly refused here rather than risked.`;
    case "paper":
      return `It earned Paper by clearing the Gate${g ? ` (${dsrProbClause(g)} ≥ 0.95, OOS ${pct(g.oosReturn)})` : ""} and is now paper-trading on live market data with NO real money. A ≥30 paper-day net-of-fee proof is the live-readiness signal; the operator decides if and when to arm it live.`;
    case "live":
      return "It's armed for live trading: it cleared the Gate and matured in Paper, and the operator armed it behind the interlocks (global toggle + venue keys + caps + kill-switch). A real order fires only while every interlock holds.";
    case "killed":
      return `It was killed — removed from the active set because its edge decayed below the floor or the operator stopped it${g && !g.passedGates ? ` (its ${dsrProbClause(g)} never cleared the 0.95 Gate)` : ""}. Its full record is KEPT — nothing is deleted, so the result stays as training data and shows in the Paper "Track record".`;
  }
}

export function AiSummary({
  summaryMd,
  stale,
  updatedAt,
  model,
  specRationale,
  stage,
  gate
}: {
  summaryMd?: string | null;
  stale?: boolean | null;
  updatedAt?: string | null;
  // Real recorded model id, when the source provides one. Falls back to the honest source label.
  model?: string | null;
  // The strategy's OWN recorded spec rationale — the honest "what this does" fallback before an agent summary
  // is written. Lifted verbatim from the spec; never generated here.
  specRationale?: string | null;
  // The lifecycle stage + the headline backtest's real Gate facts — drive the deterministic Part 2.
  stage: Stage;
  gate: GateFacts;
}) {
  // Prefer the operator-agent summary; else fall back to the spec's own rationale. The badge names the real
  // source so the reader always knows where the text came from — never invented.
  const rationale = specRationale?.trim() || null;
  const usingRationale = !summaryMd && Boolean(rationale);
  const badge = model ?? (usingRationale ? "from the spec" : "operator's agent");

  return (
    <div className="psec ai-sec">
      {/* Part 1 — What this does (agent-written, periodically refreshed; stale pill when facts moved). */}
      <div className="ai-head">
        <span
          className="ai-title"
          data-tip="What this strategy does, in plain words — what it trades and why the edge should exist. Prefers the operator's agent write-up; otherwise the strategy's own recorded rationale. Advisory, not the Gate."
        >
          What this does
        </span>
        <span className="ai-badge">{badge}</span>
        {stale ? <span className="ai-badge" style={{ color: "var(--gold)", borderColor: "oklch(0.82 0.14 85 / 0.32)" }}>stale — facts changed</span> : null}
      </div>
      {summaryMd ? (
        <>
          <p className="ai-body" style={{ whiteSpace: "pre-wrap" }}>{summaryMd}</p>
          {updatedAt ? (
            <div className="quiet" style={{ fontSize: 9.5, marginTop: 5 }}>
              written <time dateTime={updatedAt}>{fmtTz(updatedAt, { dateStyle: "medium", timeStyle: "short" })}</time>
            </div>
          ) : null}
        </>
      ) : usingRationale ? (
        <p className="ai-body" style={{ whiteSpace: "pre-wrap" }}>{rationale}</p>
      ) : (
        <p className="ai-body quiet">
          No description yet — the operator&apos;s agent writes a plain-language read from this Version&apos;s recorded facts.
          It appears here once written; the engine never auto-generates it.
        </p>
      )}

      {/* Part 2 — Why it's <Stage> (deterministic, derived from the real Gate verdict; always current). */}
      <div className="ai-head" style={{ marginTop: 14 }}>
        <span
          className="ai-title"
          data-tip="Why the strategy sits at this lifecycle stage — derived from its real Gate verdict + facts. Deterministic (not an LLM guess), so it is always current and never fabricated."
        >
          Why it&apos;s {STAGE_LABEL[stage]}
        </span>
        <span className="ai-badge">from the facts</span>
      </div>
      <p className="ai-body">{stageReason(stage, gate)}</p>
    </div>
  );
}
