// The Paper "Capital allocation" donut — where the paper wallet's INVESTED capital sits, per strategy (the
// biggest positions, with the long tail folded into one "+N more" slice so the legend stays tight). Replaces
// the honest-empty aggregate "Recent trades" box with a real wallet view; the per-fill blotter still lives on
// each strategy's detail sheet. Reuses the Iris Bento donut/legend classes (.alloc-leg/.arow/.alloc-dot).
//
// HONESTY: invested per strategy = value_usd − pnl_usd, only when BOTH real marks exist; a strategy with no
// marked value is excluded. When nothing is marked the card renders an honest empty state — never a fabricated
// allocation. Pure render (no fetch); fed the same simRows the positions table reads.

import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";
import { formatUsd, numOrNull } from "@/lib/utils";

const PALETTE = ["var(--iris)", "var(--gold)", "var(--info)", "var(--up)", "var(--down)", "var(--iris-s)"];
const TOP = 6; // show up to TOP slices; the rest collapse into one "+N more" slice so the legend never overflows.

export function WalletAllocCard({ rows }: { rows: LeaderboardRow[] }) {
  const items = rows
    .map((r) => {
      const v = numOrNull(r.value_usd);
      const p = numOrNull(r.pnl_usd);
      const invested = v !== null && p !== null ? v - p : null;
      return invested !== null && invested > 0 ? { name: r.name, amount: invested } : null;
    })
    .filter((x): x is { name: string; amount: number } => x !== null)
    .sort((a, b) => b.amount - a.amount);

  const total = items.reduce((s, x) => s + x.amount, 0);

  // Fold the long tail into a single "+N more" slice.
  let slices = items;
  if (items.length > TOP) {
    const head = items.slice(0, TOP - 1);
    const tail = items.slice(TOP - 1);
    const tailSum = tail.reduce((s, x) => s + x.amount, 0);
    slices = [...head, { name: `+${tail.length} more`, amount: tailSum }];
  }

  // Precompute each arc's cumulative offset (matches AllocDonut's stroke-dash technique).
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
      </div>
      <div className="card-body">
        {total <= 0 ? (
          <EmptyState
            title="No marked capital yet."
            hint="Once funded tracks record a marked dollar value, the paper wallet's split across strategies appears here. Nothing is fabricated."
          />
        ) : (
          <div className="wallet-alloc">
            <svg className="wdonut" width="118" height="118" viewBox="0 0 36 36" aria-label="Capital by strategy">
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
