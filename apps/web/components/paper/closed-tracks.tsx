import Link from "next/link";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatPct, formatUsd, numOrNull, signedUsd } from "@/lib/utils";

// The Paper "Track record" card (Iris Bento `.card` + `.mini-tbl`). The HONEST ledger of CLOSED paper tracks:
// when a track is killed (decayed / defunded / operator stop) it leaves the active cohort, but its record is
// KEPT here — what it was funded with and the net-of-fee P&L it finished with, like "funded $1k → closed at
// +X% / −Y%". This is the operator's "I added $1k of paper money then withdrew at a profit/loss" trace.
//
// HONESTY: NO pooled wallet, NO fabricated value — only rows that genuinely traded on paper (`has_paper_fills`)
// and are now killed (filtered upstream via isClosedPaperRow). A row with no marked dollar history renders "—",
// never a 0. Honest-empty until the first track closes. Fed the leaderboard rows the page already holds.

// finite-number guard (the shared honest-"—" helper).
const num = numOrNull;

export function ClosedTracks({ rows }: { rows: LeaderboardRow[] }) {
  // Funded (deposit) ≈ value_usd − pnl_usd; both only when real marks exist. Order: biggest |P&L| first
  // (the moves that matter), then name — a stable, decision-relevant read of the closed book.
  const ordered = [...rows].sort((a, b) => {
    const pa = num(a.pnl_usd);
    const pb = num(b.pnl_usd);
    if (pa !== null && pb !== null && pa !== pb) return Math.abs(pb) - Math.abs(pa);
    if (pa !== null && pb === null) return -1;
    if (pa === null && pb !== null) return 1;
    return a.name.localeCompare(b.name);
  });
  // The remembered aggregate: Σ realized P&L across closed tracks (only over rows that carry a real mark).
  const realized = ordered.map((r) => num(r.pnl_usd)).filter((v): v is number => v !== null);
  const netClosed = realized.length > 0 ? realized.reduce((a, b) => a + b, 0) : null;

  return (
    <div className="card dh">
      <div className="card-hdr">
        <span className="card-lbl">Track record</span>
        {netClosed !== null ? (
          <span className={cn("tab", netClosed >= 0 ? "up" : "dn")} style={{ fontSize: 11, fontWeight: 600 }}>
            {ordered.length} closed · {signedUsd(netClosed)} net
          </span>
        ) : null}
      </div>
      <div className="card-body">
        {ordered.length === 0 ? (
          <EmptyState
            title="No closed tracks yet."
            hint="When a paper track is killed or stopped, its funded amount and final net-of-fee P&L are kept here — the record survives the kill. Nothing is fabricated."
          />
        ) : (
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Funded</th>
                <th className="r">Final</th>
                <th className="r">P&amp;L</th>
                <th className="r">Return</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((row) => {
                const value = num(row.value_usd);
                const pnl = num(row.pnl_usd);
                const ret = num(row.paper_return_pct ?? row.track_return_pct);
                // Funded (the paper "deposit") = final value − net P&L, only when both real marks exist.
                const funded = value !== null && pnl !== null ? value - pnl : null;
                const cls = pnl === null ? "quiet" : pnl >= 0 ? "up" : "dn";
                return (
                  <tr key={row.version_id}>
                    <td className="pos-strat">
                      <Link href={`/strategies?v=${row.version_id}`} className="strat-link" data-tip={row.name}>
                        {row.name}
                      </Link>
                    </td>
                    <td className="r tab muted">{funded === null ? "—" : formatUsd(funded)}</td>
                    <td className="r tab">{value === null ? "—" : formatUsd(value)}</td>
                    <td className={cn("r tab", cls)}>{pnl === null ? "—" : signedUsd(pnl)}</td>
                    <td className={cn("r tab", cls)}>{ret === null ? "—" : formatPct(ret)}</td>
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
