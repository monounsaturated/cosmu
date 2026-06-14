"use client";

// The Paper "Capital allocation" donut — where the paper wallet's INVESTED capital sits. The operator picks
// the breakdown: by VENUE (default), by asset CLASS, or by STRATEGY. Biggest slices shown; the long tail folds
// into one "+N more" slice so the legend stays tight. Replaces the honest-empty aggregate "Recent trades" box
// with a real wallet view; the per-fill blotter still lives on each strategy's detail sheet.
//
// HONESTY: invested per row = value_usd − pnl_usd, only when BOTH real marks exist; a row with no marked value
// is excluded; amounts are SUMMED into the chosen bucket. When nothing is marked the card renders an honest
// empty state — never a fabricated allocation. Fed the same simRows the positions table reads.
//
// NOTE: "underlying asset" (the actual symbols a strategy trades) isn't in the LeaderboardRow contract — these
// are multi-instrument baskets — so the dimensions are the real facets we have: venue, asset class, strategy.

import { useState } from "react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatUsd, numOrNull } from "@/lib/utils";

const PALETTE = ["var(--iris)", "var(--gold)", "var(--info)", "var(--up)", "var(--down)", "var(--iris-s)"];
const TOP = 6; // show up to TOP slices; the rest collapse into one "+N more" slice so the legend never overflows.

type Dim = "venue" | "class" | "strategy";
const DIMS: { key: Dim; label: string }[] = [
  { key: "venue", label: "Venue" },
  { key: "class", label: "Class" },
  { key: "strategy", label: "Strategy" },
];
const bucketOf = (r: LeaderboardRow, dim: Dim): string =>
  dim === "venue" ? r.venue || "—" : dim === "class" ? r.asset_class || "—" : r.name;

export function WalletAllocCard({ rows }: { rows: LeaderboardRow[] }) {
  const [dim, setDim] = useState<Dim>("venue");

  // Sum invested (value_usd − pnl_usd, only when both real marks exist) into the chosen bucket.
  const byBucket = new Map<string, number>();
  for (const r of rows) {
    const v = numOrNull(r.value_usd);
    const p = numOrNull(r.pnl_usd);
    const invested = v !== null && p !== null ? v - p : null;
    if (invested === null || invested <= 0) continue;
    const k = bucketOf(r, dim);
    byBucket.set(k, (byBucket.get(k) ?? 0) + invested);
  }
  const items = [...byBucket.entries()]
    .map(([name, amount]) => ({ name, amount }))
    .sort((a, b) => b.amount - a.amount);
  const total = items.reduce((s, x) => s + x.amount, 0);

  // Fold the long tail into a single "+N more" slice.
  let slices = items;
  if (items.length > TOP) {
    const head = items.slice(0, TOP - 1);
    const tail = items.slice(TOP - 1);
    slices = [...head, { name: `+${tail.length} more`, amount: tail.reduce((s, x) => s + x.amount, 0) }];
  }

  // Precompute each arc's cumulative offset (stroke-dash technique, matches the Live AllocDonut).
  let cum = 0;
  const arcs = slices.map((s, i) => {
    const pct = total > 0 ? (s.amount / total) * 100 : 0;
    const arc = { ...s, pct, offset: -cum, color: PALETTE[i % PALETTE.length] };
    cum += pct;
    return arc;
  });

  return (
    <div className="card dh">
      <div className="card-hdr">
        <span className="card-lbl">Capital allocation</span>
        <div className="seg-sm alloc-pick">
          {DIMS.map((d) => (
            <button key={d.key} type="button" className={cn(dim === d.key && "on")} onClick={() => setDim(d.key)}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body">
        {total <= 0 ? (
          <EmptyState
            title="No marked capital yet."
            hint="Once funded tracks record a marked dollar value, the paper wallet's split appears here. Nothing is fabricated."
          />
        ) : (
          <div className="wallet-alloc">
            <svg className="wdonut" width="118" height="118" viewBox="0 0 36 36" aria-label={`Capital by ${dim}`}>
              <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--surf3)" strokeWidth="3.4" />
              {arcs.map((a) => (
                <circle
                  key={a.name}
                  cx="18"
                  cy="18"
                  r="15.9155"
                  fill="none"
                  stroke={a.color}
                  strokeWidth="3.4"
                  strokeDasharray={`${a.pct} ${100 - a.pct}`}
                  strokeDashoffset={a.offset}
                  transform="rotate(-90 18 18)"
                />
              ))}
            </svg>
            <div className="alloc-leg">
              {arcs.map((a) => (
                <div className="arow" key={a.name}>
                  <span className="alloc-dot" style={{ background: a.color }} />
                  <span className="nm" title={a.name}>
                    {a.name}
                  </span>
                  <span className="amt">{formatUsd(a.amount)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
