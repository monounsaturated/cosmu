"use client";

// intent: the lifecycle every idea goes through, and who is allowed to decide at each step.
//   Iris = an AI may act here. Green = deterministic code only. The funnel bar narrows as ideas die.

import { useInView } from "./reveal";

const STAGES = [
  { n: "01", t: "Idea", who: "AI proposes", kind: "ai", w: 100, d: "Plain English, a Pine script, or a research sweep. An LLM drafts it.", c: "419", cl: "specs written" },
  { n: "02", t: "Spec", who: "compiler checks", kind: "det", w: 88, d: "Typed rules, a required rationale, no magic numbers. Thresholds are fitted.", c: "0", cl: "look-ahead allowed" },
  { n: "03", t: "Backtest", who: "deterministic", kind: "det", w: 70, d: "Real bars, point-in-time data, every fee and slippage per venue.", c: "11+", cl: "data sources" },
  { n: "04", t: "Gate", who: "statistics decide", kind: "det", w: 22, d: "Deflated Sharpe, CSCV-PBO, holdout, regime folds, cohort FDR, must beat buy & hold.", c: "3", cl: "strict passes" },
  { n: "05", t: "Paper", who: "own sim track", kind: "det", w: 12, d: "Trades daily on live prices. Its own account, no pooled wallet.", c: "30d", cl: "proof window" },
  { n: "06", t: "Live", who: "a human launches", kind: "det", w: 5, d: "Five interlocks: toggle, keys, gate passed, caps, no kill switch.", c: "5/5", cl: "or nothing moves" },
];

export function Pipeline() {
  const [ref, seen] = useInView<HTMLDivElement>(0.25);
  return (
    <div ref={ref}>
      <div className="pipe">
        {STAGES.map((s, i) => (
          <div key={s.n} className={`cell stage ${s.kind}`}>
            <div className="step">
              <span>{s.n}</span>
              <span className={`who ${s.kind === "ai" ? "iris" : "up"}`}>{s.who}</span>
            </div>
            <h4>{s.t}</h4>
            <p>{s.d}</p>
            <div className="funnel" aria-hidden>
              <i style={{ width: seen ? `${s.w}%` : 0, transitionDelay: `${i * 140}ms` }} />
            </div>
            <div>
              <div className="count">{s.c}</div>
              <div className="quiet" style={{ fontSize: 11 }}>{s.cl}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="guard">
        <span className="chip iris"><span className="dot" /> AI allowed: propose, explain</span>
        <span className="chip up"><span className="dot" /> Code only: score, fund, trade</span>
        <span className="chip">Generating 1,000 ideas can&apos;t make a winner: cohort FDR controls for that</span>
      </div>
    </div>
  );
}
