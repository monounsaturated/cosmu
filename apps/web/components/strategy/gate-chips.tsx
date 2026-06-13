// module: GateChips — the v18 strat-sheet gate-verdict row: compact DSR / PBO / Max DD / OOS chips, each
// pass/warn-coloured against the REAL deterministic Gate thresholds (apps/engine/cosmu/config/settings.py).
// This is the glanceable cousin of the full Gate tab — four chips, not a wall of digits. Honest by
// construction: every value is the measured number off the strongest backtest; an absent value renders an
// explicit "—" with a neutral chip, never a fabricated pass. Server component.

import type { Backtest } from "@cosmu/contracts-ts";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// The REAL Gate thresholds surfaced here so the chips read against the SAME numbers the engine gates on.
const GATE = { maxPbo: 0.5, maxDrawdownPct: 0.25, minDeflatedSharpe: 0 } as const;

type Chip = { name: string; value: string; tip: string; state: "pass" | "warn" | "neutral" };

function chipsOf(bt: Backtest | null): Chip[] {
  if (!bt) {
    return [
      { name: "DSR", value: "—", tip: "Deflated Sharpe — edge after correcting for how many variants were tried.", state: "neutral" },
      { name: "PBO", value: "—", tip: "Probability the backtest is overfit.", state: "neutral" },
      { name: "Max DD", value: "—", tip: "Deepest peak-to-trough drawdown, vs the 25% kill limit.", state: "neutral" },
      { name: "OOS", value: "—", tip: "Out-of-sample return — data never seen during fitting.", state: "neutral" }
    ];
  }
  return [
    {
      name: "DSR",
      value: bt.deflated_sharpe.toFixed(2),
      tip: "Deflated Sharpe — edge after correcting for how many variants were tried. Gate: > 0.",
      state: bt.deflated_sharpe > GATE.minDeflatedSharpe ? "pass" : "warn"
    },
    {
      name: "PBO",
      value: bt.pbo.toFixed(2),
      tip: "Probability the backtest is overfit. Gate: < 0.50.",
      state: bt.pbo < GATE.maxPbo ? "pass" : "warn"
    },
    {
      name: "Max DD",
      value: `${(bt.max_dd * 100).toFixed(1)}%`,
      tip: "Deepest peak-to-trough drawdown. Gate: < 25%.",
      state: bt.max_dd < GATE.maxDrawdownPct ? "pass" : "warn"
    },
    {
      name: "OOS",
      value: `${bt.oos_return >= 0 ? "+" : ""}${(bt.oos_return * 100).toFixed(1)}%`,
      tip: "Out-of-sample return on the holdout — data never seen during fitting.",
      state: bt.oos_return >= 0 ? "pass" : "warn"
    }
  ];
}

export function GateChips({ backtest }: { backtest: Backtest | null }) {
  const chips = chipsOf(backtest);
  return (
    <div className="flex flex-wrap gap-2">
      {chips.map((c) => (
        <div
          key={c.name}
          className={cn(
            "flex min-w-[88px] flex-col gap-1 rounded-md border px-2.5 py-2",
            c.state === "pass"
              ? "border-up/35 bg-up/[0.06]"
              : c.state === "warn"
                ? "border-warn/35 bg-warn/[0.06]"
                : "border-border bg-surface-2/50"
          )}
        >
          <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">
            {c.name}
            <Tooltip content={c.tip} />
          </div>
          <div
            className={cn(
              "text-[15px] font-semibold tabular tracking-tight",
              c.state === "pass" ? "text-up" : c.state === "warn" ? "text-warn" : "text-muted"
            )}
          >
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}
