// module: KpisBox — the per-TYPE "what disposed this strategy" glance box on the strat sheet, so a human reads each
// strategy WITHOUT opening code. The codebase has TWO strategy MODELS (strategy_versions.kind):
//   • QUANT  → the deterministic Gate. We surface the COMPUTED Gate KPIs (DSR-prob / PBO / Holdout / OOS) under a
//              "type: Gate" label — the same measured numbers the Gate judged on, never a fabricated pass.
//   • LLM / CONVICTION → the conviction lane (cosmu/master/conviction.py), which can't backtest cleanly, so it
//              shows the GUARDRAILS the human signs off: thesis · confidence · named disconfirmer · max-loss · size ·
//              venue · execution, under a "type: Conviction" label, with the hard "human-armed only" note.
// HONEST: every value is bound to a REAL field (the headline backtest / holdout bundle for quant; spec.conviction
// for the conviction bet). An absent value renders an explicit "—", never a guess. Server-safe (pure render).

import type { Backtest } from "@cosmu/contracts-ts";
import { formatVenue } from "@/lib/utils";

// The REAL Gate thresholds, mirrored from gate-chips.tsx so this box reads against the SAME bars the engine gates on.
const GATE = { maxPbo: 0.5, minDsrProb: 0.95 } as const;

type Row = { key: string; val: string; tip?: string; tone?: "up" | "dn" | "gold" };

// ── The conviction declaration as the engine serialises it onto AgentSpec.conviction (Decimals → strings, confidence
// a number, expiry an ISO string). Read defensively off the raw spec Record so a partial/legacy spec never throws. ──
type ConvictionView = {
  thesis: string | null;
  confidence: number | null;
  disconfirmer: string | null;
  maxLossUsd: number | null;
  sizeUsd: number | null;
  venue: string | null;
  execution: string | null;
  expiry: string | null;
};

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return null;
}
function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

export function readConviction(spec: Record<string, unknown> | null | undefined): ConvictionView | null {
  if (!spec || typeof spec !== "object") return null;
  const c = (spec as Record<string, unknown>).conviction;
  if (!c || typeof c !== "object") return null;
  const o = c as Record<string, unknown>;
  return {
    thesis: str(o.thesis),
    confidence: num(o.confidence),
    disconfirmer: str(o.disconfirmer),
    maxLossUsd: num(o.max_loss_usd),
    sizeUsd: num(o.size_usd),
    venue: str(o.venue),
    execution: str(o.execution),
    expiry: str(o.expiry)
  };
}

function usd(n: number | null): string {
  return n === null ? "—" : `$${n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)}`;
}

// ── QUANT: the Gate KPIs, computed off the strongest backtest + the holdout bundle. Mirrors the gate-chips/phase
// table logic (DSR gates on the PROBABILITY, not the ratio); an absent number is an honest "—". ──
function gateRows(bt: Backtest | null, holdout: { passed: boolean | null }): Row[] {
  if (!bt) {
    return [
      { key: "DSR-p", val: "—", tip: "Deflated-Sharpe probability — confidence the edge is real after correcting for variants tried. Gate: ≥ 0.95." },
      { key: "PBO", val: "—", tip: "Probability the backtest is overfit. Gate: < 0.50." },
      { key: "Holdout", val: "—", tip: "Did the edge survive the untouched one-shot out-of-sample data." },
      { key: "OOS", val: "—", tip: "Out-of-sample return on data never seen during fitting." }
    ];
  }
  const dsrProb = bt.deflated_sharpe_prob ?? null;
  const dsrPass = dsrProb !== null ? dsrProb >= GATE.minDsrProb : bt.passed_gates;
  const dsrVal = dsrProb !== null ? dsrProb.toFixed(2) : bt.passed_gates ? "≥0.95" : "<0.95";
  const oosPct = bt.oos_return * 100;
  return [
    {
      key: "DSR-p",
      val: dsrVal,
      tone: dsrPass ? "up" : "gold",
      tip: `Deflated-Sharpe PROBABILITY — the 0-to-1 confidence the edge is real after discounting how many variants were tried. THIS is the number the Gate's 0.95 bar checks (the raw ratio is ${bt.deflated_sharpe.toFixed(2)}).`
    },
    { key: "PBO", val: bt.pbo.toFixed(2), tone: bt.pbo < GATE.maxPbo ? "up" : "gold", tip: "Probability of Backtest Overfitting — chance the result is curve-fit noise. Gate: < 0.50." },
    {
      key: "Holdout",
      val: holdout.passed === null ? "—" : holdout.passed ? "Held" : "Failed",
      tone: holdout.passed === null ? undefined : holdout.passed ? "up" : "dn",
      tip: "The untouched, one-shot out-of-sample holdout — the most honest 'did the edge survive data it was never fit to'."
    },
    { key: "OOS", val: `${oosPct >= 0 ? "+" : ""}${oosPct.toFixed(1)}%`, tone: oosPct >= 0 ? "up" : "dn", tip: "Out-of-sample return on the holdout — data never seen during fitting." }
  ];
}

function GateBox({ backtest, holdout }: { backtest: Backtest | null; holdout: { passed: boolean | null } }) {
  const rows = gateRows(backtest, holdout);
  return (
    <div className="psec">
      <div className="psec-title">
        Gate KPIs <span className="badge badge-muted" data-tip="A typed quant strategy — disposed by the deterministic Gate (DSR / PBO / holdout / OOS), the statistical edge test.">type: Gate</span>
      </div>
      <div className="gate-chips">
        {rows.map((r) => (
          <div key={r.key} className={r.tone === "up" ? "gate-chip pass" : r.tone === "gold" || r.tone === "dn" ? "gate-chip warn" : "gate-chip"}>
            <div className="gc-name">
              {r.key} {r.tip ? <span className="gc-q" data-tip={r.tip}>?</span> : null}
            </div>
            <div className={`gc-val ${r.tone === "up" ? "gc-pass" : r.tone === "gold" || r.tone === "dn" ? "gc-warn" : ""}`}>{r.val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── LLM / CONVICTION: the guardrails + reviewable case. Honest empty state when a kind='llm' strategy carries no
// conviction declaration yet (it's observe-only — it proposes no bet). ──
function ConvictionBox({ conviction }: { conviction: ConvictionView | null }) {
  if (!conviction) {
    return (
      <div className="psec">
        <div className="psec-title">
          Conviction <span className="badge badge-iris" data-tip="An LLM/agentic strategy — disposed by the conviction lane (guardrails + human review), never the statistical Gate.">type: Conviction</span>
        </div>
        <p className="quiet" style={{ fontSize: 11 }}>Observe-only — no conviction bet declared yet. The agent reasons and records, but proposes no fundable bet until a thesis + guardrails (max-loss, venue, execution) are set.</p>
      </div>
    );
  }
  const rows: Row[] = [
    { key: "Confidence", val: conviction.confidence === null ? "—" : `${(conviction.confidence * 100).toFixed(0)}%`, tip: "The agent/operator's stated confidence in the thesis — the conviction lane needs a floor (default ≥ 55%) to even propose." },
    { key: "Max loss", val: usd(conviction.maxLossUsd), tone: "gold", tip: "The HARD cap on what this single bet may lose, in USD — the worst case the human signs off. The lane rejects anything over the operator's per-bet cap." },
    { key: "Size", val: usd(conviction.sizeUsd), tip: "The intended stake — small by design (the conviction lane is intentionally tiny, ≤ the max-loss)." },
    { key: "Venue", val: conviction.venue ? formatVenue(conviction.venue) : "—", tip: "Where the bet fills — must be a live-capable venue (IBKR / Kraken / Polymarket), never a paper-only one like Alpaca." },
    { key: "Execution", val: conviction.execution ? conviction.execution : "—", tip: "Maker or taker — declared so the fee/realism is explicit." }
  ];
  if (conviction.expiry) rows.push({ key: "Expiry", val: conviction.expiry.slice(0, 10), tip: "After this date the conviction is stale — the lane will not propose it." });
  return (
    <div className="psec">
      <div className="psec-title">
        Conviction guardrails <span className="badge badge-iris" data-tip="An LLM/agentic strategy — disposed by the conviction lane (guardrails + human review), never the statistical Gate.">type: Conviction</span>
        <span className="badge badge-gold" style={{ marginLeft: 6 }} data-tip="The conviction lane only PROPOSES — it moves no money and places no order. A human must arm any real capital.">human-armed only</span>
      </div>
      {conviction.thesis ? (
        <p style={{ fontSize: 11, lineHeight: 1.5, margin: "0 0 6px" }}>
          <span className="block-key" style={{ width: "auto", marginRight: 6 }}>Thesis</span>
          {conviction.thesis}
        </p>
      ) : null}
      {conviction.disconfirmer ? (
        <p className="quiet" style={{ fontSize: 11, lineHeight: 1.5, margin: "0 0 8px" }}>
          <span className="block-key" style={{ width: "auto", marginRight: 6 }}>Disconfirmer</span>
          {conviction.disconfirmer}
        </p>
      ) : null}
      <div className="blocks">
        {rows.map((r) => (
          <div key={r.key} className="block-row">
            <span className="block-key" data-tip={r.tip}>{r.key}</span>
            <span className={`block-val ${r.tone === "gold" ? "gold" : ""}`}>{r.val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// The per-type KPIs box. `kind='llm'` → the conviction guardrails; everything else → the Gate KPIs. Defaults to the
// Gate box (every strategy is quant today), so the conviction box only appears for a genuine LLM/conviction strategy.
export function KpisBox({
  kind,
  spec,
  backtest,
  holdout
}: {
  kind?: "quant" | "llm" | null;
  spec: Record<string, unknown> | null | undefined;
  backtest: Backtest | null;
  holdout: { passed: boolean | null };
}) {
  if (kind === "llm") return <ConvictionBox conviction={readConviction(spec)} />;
  return <GateBox backtest={backtest} holdout={holdout} />;
}
