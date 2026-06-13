import { Activity, ShieldCheck } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { formatPct } from "@/lib/utils";

// The SIM-vs-backtest divergence badge for one paper track. HONEST by construction: it reads the
// leaderboard contract's `divergence_status` (computed in master/divergence.py) and renders one of three calm,
// premium, NO-emoji states:
//   - "tracking":     the marked paper return is still following its backtest → a quiet "up" confirmation.
//   - "diverging":    the marked paper return has drifted off its backtest by more than the monitoring band →
//                     an early warning (alpha-decay / regime-shift). Shows the signed gap so the read is honest.
//   - "insufficient": the track hasn't accrued enough marked days to compare → an honest, alarm-free empty state.
// This is MONITORING ONLY. It never gates and never moves money — it is a glance, surfaced for the operator.
export function DivergenceBadge({ row }: { row: LeaderboardRow }) {
  const status = row.divergence_status ?? "insufficient";

  if (status === "insufficient") {
    // Honest empty state: too few marked days to compare against the backtest. No alarm, no fabricated gap.
    return (
      <Tooltip content="Too few marked paper days to compare against the backtest yet. The divergence check needs a short stretch of real paper history before it can read whether the live track is still following its backtest.">
        <Badge variant="muted">
          <Activity className="size-3" /> divergence · not enough data
        </Badge>
      </Tooltip>
    );
  }

  const gap = typeof row.divergence_gap_pct === "number" ? row.divergence_gap_pct : null;
  const gapLabel = gap !== null ? formatPct(gap) : "—";

  if (status === "diverging") {
    return (
      <Tooltip content="The marked paper return has drifted off its backtest by more than the monitoring band — an early warning of alpha-decay or a regime shift. The gap is forward return minus the backtest pro-rated to the same elapsed window. Monitoring only; this never gates or moves money.">
        <Badge variant="warn">
          <Activity className="size-3" /> diverging · {gapLabel}
        </Badge>
      </Tooltip>
    );
  }

  // status === "tracking"
  return (
    <Tooltip content="The marked paper return is still following its backtest, within the monitoring band. The gap is forward return minus the backtest pro-rated to the same elapsed window.">
      <Badge variant="up">
        <ShieldCheck className="size-3" /> tracking · {gapLabel}
      </Badge>
    </Tooltip>
  );
}
