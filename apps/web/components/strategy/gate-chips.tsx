// module: GateChips — the v18 strat-sheet gate-verdict row (Iris Bento `.gate-chips` → four
// `.gate-chip`s: DSR / PBO / Max DD / OOS). Each chip carries the (?) `.gc-q` data-tip and a value
// coloured pass/warn against the REAL deterministic Gate thresholds (apps/engine/cosmu/config/settings.py).
// The glanceable cousin of the full Gate tab. HONEST: every value is the measured number off the strongest
// backtest; an absent value renders an explicit "—" in a neutral chip, never a fabricated pass. Server-safe.

import type { Backtest } from "@cosmu/contracts-ts";

// The REAL Gate thresholds surfaced here so the chips read against the SAME numbers the engine gates on.
const GATE = { maxPbo: 0.5, maxDrawdownPct: 0.25, minDeflatedSharpe: 0 } as const;

type Chip = { name: string; value: string; tip: string; valueClass: string; pass: boolean | null };

function chipsOf(bt: Backtest | null): Chip[] {
  if (!bt) {
    return [
      { name: "DSR", value: "—", tip: "Deflated Sharpe — edge after correcting for how many variants were tried.", valueClass: "", pass: null },
      { name: "PBO", value: "—", tip: "Probability the backtest is overfit.", valueClass: "", pass: null },
      { name: "Max DD", value: "—", tip: "Deepest peak-to-trough drawdown, vs the 25% kill limit.", valueClass: "", pass: null },
      { name: "OOS", value: "—", tip: "Out-of-sample return — data never seen during fitting.", valueClass: "", pass: null }
    ];
  }
  const dsrPass = bt.deflated_sharpe > GATE.minDeflatedSharpe;
  const pboPass = bt.pbo < GATE.maxPbo;
  const ddPass = bt.max_dd < GATE.maxDrawdownPct;
  const oosPass = bt.oos_return >= 0;
  return [
    {
      name: "DSR",
      value: bt.deflated_sharpe.toFixed(2),
      tip: "Deflated Sharpe — edge after correcting for how many variants were tried. Gate: > 0.",
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
