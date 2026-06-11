import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { MetricCard, GaugeBar } from "@/components/ui/viz";
import { formatPct } from "@/lib/utils";

// The Simulation cohort at a glance. Four honest read-outs over the real tracks the Gate has funded:
//   - Tracks in Simulation: how many cleared the Gate and are now marked on live data.
//   - Live-ready (matured): how many have crossed the +30-day net-positive threshold (live_ready === true).
//   - Tracking / Diverging: the divergence split — how many are still following their backtest vs drifting.
//   - Median forward return: the COHORT's real net-of-fee forward return, median across marked tracks.
// HONESTY: every number is derived from the rows the engine returned. A cohort with no marked forward
// history shows a plain "—" for the median, never a fabricated curve. The maturity gauge reads the real
// share that has matured; nothing is padded.
//
// Live-ready threshold mirrors the engine's FORWARD_TEST_MIN_DAYS (30 net-positive forward days).
const LIVE_READY_DAYS = 30;

export function SimSummary({ rows }: { rows: LeaderboardRow[] }) {
  const total = rows.length;
  const matured = rows.filter((r) => r.live_ready).length;
  const tracking = rows.filter((r) => r.divergence_status === "tracking").length;
  const diverging = rows.filter((r) => r.divergence_status === "diverging").length;

  // Median forward return across tracks that have ACTUALLY accrued a marked forward number. A just-funded
  // (null) track is excluded from the median rather than counted as a fabricated 0.
  const marked = rows
    .map((r) => r.forward_return_pct)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
    .sort((a, b) => a - b);
  const medianFwd =
    marked.length === 0
      ? null
      : marked.length % 2 === 1
        ? marked[(marked.length - 1) / 2]
        : (marked[marked.length / 2 - 1] + marked[marked.length / 2]) / 2;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Tracks in Simulation"
        tone="iris"
        value={total}
        hint="cleared the Gate · marked on live data"
      />
      <MetricCard
        label="Live-ready"
        tone={matured > 0 ? "up" : "muted"}
        value={
          <span className={matured > 0 ? "text-foreground" : "text-muted"}>
            {matured}
            <span className="text-[13px] font-normal text-quiet"> / {total}</span>
          </span>
        }
        hint={
          <div className="space-y-1.5">
            <GaugeBar value={matured} max={Math.max(1, total)} marker={1} tone={matured > 0 ? "up" : "muted"} />
            <span className="text-quiet">matured past +{LIVE_READY_DAYS}d net-positive</span>
          </div>
        }
      />
      <MetricCard
        label="Tracking / Diverging"
        tone={diverging > 0 ? "warn" : "up"}
        value={
          <span className="tabular">
            <span className="text-up">{tracking}</span>
            <span className="px-1 text-quiet">/</span>
            <span className={diverging > 0 ? "text-warn" : "text-muted"}>{diverging}</span>
          </span>
        }
        hint="still following backtest vs drifting off it"
      />
      <MetricCard
        label="Median forward"
        tone={medianFwd === null ? "muted" : medianFwd >= 0 ? "up" : "down"}
        value={
          medianFwd === null ? (
            <span className="text-muted">—</span>
          ) : (
            <span className={medianFwd >= 0 ? "text-up" : "text-down"}>{formatPct(medianFwd)}</span>
          )
        }
        hint={
          medianFwd === null
            ? "no marked forward history yet"
            : `median net-of-fee across ${marked.length} marked track${marked.length === 1 ? "" : "s"}`
        }
      />
    </div>
  );
}
