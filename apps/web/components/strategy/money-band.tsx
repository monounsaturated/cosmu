// module: MoneyBand — the v18 strategy-sheet money band: a four-cell row (Value · Invested · P&L · Fees)
// that answers "what is this track worth and what has it cost" at a glance. HONEST BY CONSTRUCTION: the
// strategy-detail contract carries only the trade blotter, so only P&L (cumulative realized cash flow off
// the fills) and Fees (summed Execution.fee) are real numbers here. Value and Invested are NOT on this
// contract — they are rendered as an explicit "—" with a quiet "not on track" note, never fabricated or
// faked from 0. Server component; every value is passed in already-derived.
//
// All dollar values render through formatUsd so the $ is always shown; the % sits alongside P&L.

import { cn, formatUsd } from "@/lib/utils";

export type MoneyBandData = {
  // Marked value of the track now — null when the contract does not carry it (the common case for
  // paper/backtest detail, which has no marked equity field).
  valueUsd: number | null;
  // Capital committed to the track — null when not on the contract.
  investedUsd: number | null;
  // Realized P&L off the fills (sells add, buys + fees subtract). null when there are no fills.
  pnlUsd: number | null;
  // P&L as a percent of invested, when both are known; else null.
  pnlPct: number | null;
  // Total fees paid across the fills. null when there are no fills.
  feesUsd: number | null;
  // Honest sub-line for the P&L cell — e.g. "18d · realized" — null to omit.
  pnlSub?: string | null;
  // Honest sub-line for the fees cell — e.g. "off real fills". null to omit.
  feesSub?: string | null;
};

function tone(v: number | null): "up" | "down" | "flat" {
  if (v === null || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

function Cell({
  label,
  value,
  sub,
  valueTone = "flat"
}: {
  label: string;
  value: string;
  sub?: string | null;
  valueTone?: "up" | "down" | "flat";
}) {
  return (
    <div className="min-w-0 flex-1 px-4 py-3.5">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">{label}</div>
      <div
        className={cn(
          "mt-1 text-[19px] font-semibold tabular tracking-tight",
          valueTone === "up" ? "text-up" : valueTone === "down" ? "text-down" : "text-foreground"
        )}
      >
        {value}
      </div>
      {sub ? <div className={cn("mt-0.5 text-[11px]", valueTone === "up" ? "text-up/80" : valueTone === "down" ? "text-down/80" : "text-quiet")}>{sub}</div> : null}
    </div>
  );
}

export function MoneyBand({ data }: { data: MoneyBandData }) {
  const pnlTone = tone(data.pnlUsd);
  const pnlValue =
    data.pnlUsd === null
      ? "—"
      : `${data.pnlUsd >= 0 ? "+" : "-"}${formatUsd(Math.abs(data.pnlUsd), 2)}`;
  const pnlSub =
    data.pnlPct !== null
      ? `${data.pnlPct >= 0 ? "+" : ""}${data.pnlPct.toFixed(1)}%${data.pnlSub ? ` · ${data.pnlSub}` : ""}`
      : data.pnlSub ?? null;

  return (
    <div className="grid grid-cols-2 divide-x divide-y divide-border/60 overflow-hidden rounded-lg border border-border/70 card-grad sm:grid-cols-4 sm:divide-y-0">
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
      <Cell label="P&L" value={pnlValue} sub={pnlSub} valueTone={pnlTone} />
      <Cell
        label="Fees"
        value={data.feesUsd !== null ? formatUsd(data.feesUsd, 2) : "—"}
        sub={data.feesUsd !== null ? data.feesSub ?? "off real fills" : "no fills yet"}
      />
    </div>
  );
}
