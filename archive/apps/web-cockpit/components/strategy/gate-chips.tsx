// module: GateChips — the v18 strat-sheet gate-verdict row (Iris Bento `.gate-chips` → four
// `.gate-chip`s: DSR / PBO / Max DD / OOS). Each chip carries the (?) `.gc-q` data-tip and a value
// coloured pass/warn against the REAL deterministic Gate thresholds (apps/engine/cosmu/config/settings.py).
// The glanceable cousin of the full Gate tab. HONEST: every value is the measured number off the strongest
// backtest; an absent value renders an explicit "—" in a neutral chip, never a fabricated pass. Server-safe.

import type { Backtest } from "@cosmu/contracts-ts";

// The REAL Gate thresholds surfaced here so the chips read against the SAME numbers the engine gates on. The DSR
// chip gates on the deflated-Sharpe PROBABILITY (≥ 0.95), NOT the deflated-Sharpe ratio — the ratio is a ranking
// number that can exceed 1.0, so comparing it to the 0.95 PROBABILITY bar reads as a contradiction.
const GATE = { maxPbo: 0.5, maxDrawdownPct: 0.25, minDsrProb: 0.95 } as const;

type Chip = { name: string; value: string; tip: string; valueClass: string; pass: boolean | null };

function chipsOf(bt: Backtest | null): Chip[] {
  if (!bt) {
    return [
      { name: "DSR-p", value: "—", tip: "Deflated-Sharpe probability — the confidence the edge is real after correcting for how many variants were tried.", valueClass: "", pass: null },
      { name: "PBO", value: "—", tip: "Probability the backtest is overfit.", valueClass: "", pass: null },
      { name: "Max DD", value: "—", tip: "Deepest peak-to-trough drawdown, vs the 25% kill limit.", valueClass: "", pass: null },
      { name: "OOS", value: "—", tip: "Out-of-sample return — data never seen during fitting.", valueClass: "", pass: null }
    ];
  }
  // The GATED number is the deflated-Sharpe PROBABILITY (deflated_sharpe_prob, the 0–1 value the 0.95 bar checks),
  // recomputed by the engine from this backtest's survival inputs. When absent (pre-migration / arm rows) fall back
  // to the binary verdict (≥/< 0.95) off passed_gates rather than fabricating a number — never show the ratio here.
  const dsrProb = bt.deflated_sharpe_prob ?? null;
  const dsrPass = dsrProb !== null ? dsrProb >= GATE.minDsrProb : bt.passed_gates;
  const dsrValue = dsrProb !== null ? dsrProb.toFixed(2) : bt.passed_gates ? "≥0.95" : "<0.95";
  const pboPass = bt.pbo < GATE.maxPbo;
  const ddPass = bt.max_dd < GATE.maxDrawdownPct;
  const oosPass = bt.oos_return >= 0;
  return [
    {
      name: "DSR-p",
      value: dsrValue,
      tip: `Deflated-Sharpe PROBABILITY — the 0-to-1 confidence the edge is real after correcting for how many variants were tried. THIS is the number the Gate's 0.95 bar checks, not the deflated-Sharpe ratio (${bt.deflated_sharpe.toFixed(2)}). Gate: ≥ 0.95.`,
      valueClass: dsrPass ? "gc-pass" : "gc-warn",
      pass: dsrPass
    },
    {
      name: "PBO",
      value: bt.pbo.toFixed(2),
      tip: "Probability the backtest is overfit. Gate: < 0.50.",
      valueClass: pboPass ? "gc-pass" : "gc-warn",
      pass: pboPass
    },
    {
      name: "Max DD",
      value: `${(bt.max_dd * 100).toFixed(1)}%`,
      tip: "Deepest peak-to-trough drawdown. Gate: < 25%.",
      valueClass: ddPass ? "gc-pass" : "gc-warn",
      pass: ddPass
    },
    {
      name: "OOS",
      value: `${bt.oos_return >= 0 ? "+" : ""}${(bt.oos_return * 100).toFixed(1)}%`,
      tip: "Out-of-sample return on the holdout — data never seen during fitting.",
      valueClass: oosPass ? "gc-pass" : "gc-warn",
      pass: oosPass
    }
  ];
}

export function GateChips({ backtest }: { backtest: Backtest | null }) {
  const chips = chipsOf(backtest);
  return (
    <div className="gate-chips">
      {chips.map((c) => (
        <div key={c.name} className={c.pass === true ? "gate-chip pass" : c.pass === false ? "gate-chip warn" : "gate-chip"}>
          <div className="gc-name">
            {c.name} <span className="gc-q" data-tip={c.tip}>?</span>
          </div>
          <div className={`gc-val ${c.valueClass}`}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
