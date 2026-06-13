// module: MoneyBand — the v18 strat-sheet money band (Iris Bento `.money-band` → four `.mb-cell`s:
// Value · Invested · P&L · Fees). It answers "what is this track worth and what has it cost" at a glance.
// HONEST BY CONSTRUCTION: the strategy-detail contract carries only the trade blotter, so only P&L
// (cumulative realized cash flow off the fills) and Fees (summed Execution.fee) are real numbers here.
// Value and Invested are NOT on this contract — they render an explicit "—" in a quiet `.mb-sub`, never
// fabricated or faked from 0. Server-safe; every value is passed in already-derived. All dollar values
// render through formatUsd so the $ is always shown.

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
  const pnlValue = data.pnlUsd === null ? "—" : `${data.pnlUsd >= 0 ? "+" : "-"}${formatUsd(Math.abs(data.pnlUsd), 2)}`;
  const pnlSub =
    data.pnlPct !== null
      ? `${data.pnlPct >= 0 ? "+" : ""}${data.pnlPct.toFixed(1)}%${data.pnlSub ? ` · ${data.pnlSub}` : ""}`
      : data.pnlSub ?? null;

  return (
    <div className="money-band">
      <Cell
        label="Value"
        value={data.valueUsd !== null ? formatUsd(data.valueUsd, 2) : "—"}
        sub={data.valueUsd !== null ? "marked now" : "not on track record"}
      />
      <Cell
        label="Invested"
        value={data.investedUsd !== null ? formatUsd(data.investedUsd, 2) : "—"}
        sub={data.investedUsd !== null ? "committed" : "not on track record"}
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
