"use client";

// The Paper "Open positions" card (Iris Bento `.card` + `.mini-tbl`, mirrors the mockup's positions()).
// ONE row per funded paper track: name (links to its detail sheet) · pair (class · venue · tf) · size
// (invested) · value (current mark) · P&L ($ + %). The first 4 rows show; "See all →" reveals the rest
// (the `.dash-extra` / `.dash-open` mechanic from the mockup).
//
// HONESTY: a track with no marked dollar value (value_usd / pnl_usd === null) renders "—" in those cells —
// never a 0. If NO track carries any dollar mark, the table collapses to an honest empty state. Nothing is
// fabricated; the per-fill blotter lives on each strategy's detail sheet.

import { useState } from "react";
import Link from "next/link";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatPct, formatUsd, numOrNull } from "@/lib/utils";

const LIM = 4;

// finite-number guard (the shared honest-"—" helper).
const num = numOrNull;

export function PaperPositions({ rows }: { rows: LeaderboardRow[] }) {
  const [open, setOpen] = useState(false);

  // Stable, decision-relevant order: biggest absolute marked P&L first, then by name.
  const ordered = [...rows].sort((a, b) => {
    const pa = num(a.pnl_usd);
    const pb = num(b.pnl_usd);
    if (pa !== null && pb !== null && pa !== pb) return Math.abs(pb) - Math.abs(pa);
    if (pa !== null && pb === null) return -1;
    if (pa === null && pb !== null) return 1;
    return a.name.localeCompare(b.name);
  });

  const anyMarked = rows.some((r) => num(r.value_usd) !== null || num(r.pnl_usd) !== null);

  return (
    <div className={cn("card dh", open && "dash-open")}>
      <div className="card-hdr">
        <span className="card-lbl">Open positions</span>
        {anyMarked && ordered.length > LIM ? (
          <button className="seeall-btn" onClick={() => setOpen((v) => !v)}>
            {open ? "Show less" : "See all →"}
          </button>
        ) : null}
      </div>
      <div className="card-body">
        {!anyMarked ? (
          <EmptyState
            title="No marked track value yet."
            hint="A track shows its deployed capital and net-of-fee P&L here once it accrues marked history. Open a track to see its per-fill blotter."
          />
        ) : (
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Pair</th>
                <th className="r">Size</th>
                <th className="r">Value</th>
                <th className="r">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((row, i) => {
                const value = num(row.value_usd);
                const pnl = num(row.pnl_usd);
                const pct = num(row.pnl_pct);
                // Invested = current value − net P&L, only when both real marks exist.
                const invested = value !== null && pnl !== null ? value - pnl : null;
                const pnlCls = pnl === null ? "quiet" : pnl >= 0 ? "up" : "dn";
                return (
                  <tr key={row.version_id} className={cn(i >= LIM && "dash-extra")}>
                    <td>
                      <Link href={`/strategies?v=${row.version_id}`} className="strat-link">
                        {row.name}
                      </Link>
                    </td>
                    <td className="muted">
                      {row.asset_class} · {row.venue} · {row.timeframe}
                    </td>
                    <td className="r tab muted">{invested === null ? "—" : formatUsd(invested)}</td>
                    <td className="r tab">{value === null ? "—" : formatUsd(value)}</td>
                    <td className={cn("r tab", pnlCls)}>
                      {pnl === null ? "—" : formatUsd(pnl)}
                      {pct !== null ? <span> {formatPct(pct)}</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
