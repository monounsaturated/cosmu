import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { formatPct } from "@/lib/utils";

// The SIM-vs-backtest divergence badge for one paper track (Iris Bento). HONEST by construction: it reads
// the leaderboard contract's `divergence_status` (computed in master/divergence.py) and renders one of three
// calm bento badges with a `data-tip` for the explanation:
//   - "tracking":     the marked paper return is still following its backtest → a quiet "up" confirmation.
//   - "diverging":    the marked paper return has drifted past the monitoring band → an early warning. Shows
//                     the signed gap so the read is honest.
//   - "insufficient": too few marked days to compare → an honest, alarm-free muted badge.
// MONITORING ONLY — it never gates and never moves money. It is a glance, surfaced for the operator.
export function DivergenceBadge({ row }: { row: LeaderboardRow }) {
  const status = row.divergence_status ?? "insufficient";

  if (status === "insufficient") {
    return (
      <span
        className="badge badge-muted"
        data-tip="Too few marked paper days to compare against the backtest yet. The divergence check needs a short stretch of real paper history before it can read whether the live track is still following its backtest."
      >
        divergence · not enough data
      </span>
    );
  }

  const gap = typeof row.divergence_gap_pct === "number" ? row.divergence_gap_pct : null;
  const gapLabel = gap !== null ? formatPct(gap) : "—";

  if (status === "diverging") {
    return (
      <span
        className="badge badge-gold"
        data-tip="The marked paper return has drifted off its backtest by more than the monitoring band — an early warning of alpha-decay or a regime shift. The gap is forward return minus the backtest pro-rated to the same elapsed window. Monitoring only; this never gates or moves money."
      >
        diverging · {gapLabel}
      </span>
    );
  }

  // status === "tracking"
  return (
    <span
      className="badge badge-up"
      data-tip="The marked paper return is still following its backtest, within the monitoring band. The gap is forward return minus the backtest pro-rated to the same elapsed window."
    >
      tracking · {gapLabel}
    </span>
  );
}
