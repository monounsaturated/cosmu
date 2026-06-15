// module: MoneyBand — the v18 strat-sheet money band (Iris Bento `.money-band` → four `.mb-cell`s:
// Value · Invested · P&L · Fees). It answers "what is this track worth and what has it cost" at a glance.
// HONEST BY CONSTRUCTION: every figure is passed in already-derived from the engine's MARKED forward money
// (StrategyDetailResponse value_usd / invested_usd / pnl_usd — the SAME source the leaderboard serves), never
// the fills' cash flow. Until the track is marked the caller passes null and the cell renders an explicit "—"
// in a quiet `.mb-sub`, never fabricated or faked from 0. Exact $0 P&L renders NEUTRAL (no sign, no colour) —
// a flat track is honestly flat, not a gain. Server-safe; all dollar values render through formatUsd.

import { cn, formatUsd } from "@/lib/utils";

export type MoneyBandData = {
  // Marked value of the track now — null when the contract does not carry it (the common case).
  valueUsd: number | null;
  // Capital committed to the track — null when not on the contract.
  investedUsd: number | null;
  // Realized P&L off the fills (sells add, buys + fees subtract). null when there are no fills.
  pnlUsd: number | null;
  // P&L as a percent of invested, when both are known; else null.
  pnlPct: number | null;
  // Total fees paid across the fills. null when there are no fills.
  feesUsd: number | null;
  // Honest sub-line for the P&L cell — e.g. "18d · realized". null to omit (then "—").
  pnlSub?: string | null;
  // Honest sub-line for the fees cell — e.g. "off real fills". null to omit.
  feesSub?: string | null;
};

function toneClass(v: number | null): string {
  if (v === null || v === 0) return "";
  return v > 0 ? "up" : "dn";
}

function Cell({ label, value, sub, valueClass }: { label: string; value: string; sub?: string | null; valueClass?: string }) {
  return (
    <div className="mb-cell">
      <div className="mb-label">{label}</div>
      <div className={cn("mb-val", valueClass)}>{value}</div>
      {sub ? <div className="mb-sub">{sub}</div> : null}
    </div>
  );
}

export function MoneyBand({ data }: { data: MoneyBandData }) {
  const pnlClass = toneClass(data.pnlUsd);
  // Exact $0 renders neutral (no +/- sign) — a flat track is flat, not a gain. Non-zero carries its sign.
  const pnlValue =
    data.pnlUsd === null
      ? "—"
      : data.pnlUsd === 0
        ? formatUsd(0, 2)
        : `${data.pnlUsd > 0 ? "+" : "-"}${formatUsd(Math.abs(data.pnlUsd), 2)}`;
  const pctText =
    data.pnlPct === null
      ? null
      : data.pnlPct === 0
        ? "0.0%"
        : `${data.pnlPct > 0 ? "+" : "-"}${Math.abs(data.pnlPct).toFixed(1)}%`;
  const pnlSub = pctText !== null ? `${pctText}${data.pnlSub ? ` · ${data.pnlSub}` : ""}` : data.pnlSub ?? null;

  return (
    <div className="money-band">
      <Cell
        label="Value"
        value={data.valueUsd !== null ? formatUsd(data.valueUsd, 2) : "—"}
        sub={data.valueUsd !== null ? "marked now" : "not marked yet"}
      />
      <Cell
        label="Invested"
        value={data.investedUsd !== null ? formatUsd(data.investedUsd, 2) : "—"}
        sub={data.investedUsd !== null ? "committed" : "not marked yet"}
      />
      <Cell label="P&L" value={pnlValue} sub={pnlSub} valueClass={pnlClass} />
      <Cell
        label="Fees"
        value={data.feesUsd !== null ? formatUsd(data.feesUsd, 2) : "—"}
        sub={data.feesUsd !== null ? data.feesSub ?? "off real fills" : "no fills yet"}
      />
    </div>
  );
}
