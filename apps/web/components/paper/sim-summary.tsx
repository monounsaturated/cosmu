import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { MetricCard, GaugeBar } from "@/components/ui/viz";
import { cn, formatPct, formatUsd } from "@/lib/utils";

// The Paper cohort KPI row (v18 kpi-grid). Four honest, money-first read-outs over the REAL tracks the
// Gate has funded — chart-on-top, then this strip, then the per-track cards:
//   - Invested:    Σ of the capital deployed across paper tracks (current value − net P&L, per track).
//   - P&L:         Σ of net-of-fee P&L in $ across marked tracks, with the cohort % alongside (always $).
//   - Tracks:      how many cleared the Gate and are now marked on live data.
//   - Live-ready:  how many have crossed the +30-day net-positive threshold (live_ready === true), with a
//                  maturity gauge reading the REAL matured share.
//
// HONESTY: every number is derived from the rows the engine returned. The $ aggregates are summed ONLY
// over tracks that carry a real value_usd / pnl_usd — a cohort with no marked dollar history shows a plain
// "—", never a fabricated 0 or curve. The divergence split (tracking / diverging) rides in the P&L hint so
// the operator still sees it at a glance without a fifth box.
//
// Live-ready threshold mirrors the engine's PAPER_MIN_DAYS (30 net-positive paper days).
const LIVE_READY_DAYS = 30;

// A finite-number guard — null / NaN / non-finite never enters an aggregate.
function num(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function SimSummary({ rows }: { rows: LeaderboardRow[] }) {
  const total = rows.length;
  const matured = rows.filter((r) => r.live_ready).length;
  const tracking = rows.filter((r) => r.divergence_status === "tracking").length;
  const diverging = rows.filter((r) => r.divergence_status === "diverging").length;

  // Σ over tracks that carry REAL dollar marks. A track with null value_usd / pnl_usd is excluded from the
  // sum (never counted as a fabricated 0). If no track carries a dollar mark, the aggregate is null → "—".
  const valued = rows.map((r) => num(r.value_usd)).filter((v): v is number => v !== null);
  const pnls = rows.map((r) => num(r.pnl_usd)).filter((v): v is number => v !== null);
  const totalValue = valued.length > 0 ? valued.reduce((a, b) => a + b, 0) : null;
  const totalPnl = pnls.length > 0 ? pnls.reduce((a, b) => a + b, 0) : null;
  // Invested = current value − net P&L, summed only over tracks that carry BOTH marks.
  const investedParts = rows
    .map((r) => {
      const v = num(r.value_usd);
      const p = num(r.pnl_usd);
      return v !== null && p !== null ? v - p : null;
    })
    .filter((v): v is number => v !== null);
  const invested = investedParts.length > 0 ? investedParts.reduce((a, b) => a + b, 0) : null;
  // Cohort % = total net P&L over total invested. Only when both real aggregates exist and invested > 0.
  const cohortPct = totalPnl !== null && invested !== null && invested > 0 ? (totalPnl / invested) * 100 : null;

  const pnlTone = totalPnl === null ? "muted" : totalPnl > 0 ? "up" : totalPnl < 0 ? "down" : "muted";

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {/* Invested — Σ deployed capital across paper tracks (always $). */}
      <MetricCard
        label="Invested"
        tone="iris"
        value={
          invested === null ? (
            <span className="text-muted">—</span>
          ) : (
            <span className="text-foreground">{formatUsd(invested)}</span>
          )
        }
        hint={
          invested === null
            ? "no marked track value yet"
            : `across ${investedParts.length} marked track${investedParts.length === 1 ? "" : "s"} · standalone, no pooled wallet`
        }
      />

      {/* P&L — Σ net-of-fee dollar P&L, with the cohort % alongside. The divergence split rides in the hint. */}
      <MetricCard
        label="P&L"
        tone={pnlTone}
        value={
          totalPnl === null ? (
            <span className="text-muted">—</span>
          ) : (
            <span className={totalPnl >= 0 ? "text-up" : "text-down"}>{formatUsd(totalPnl)}</span>
          )
        }
        delta={
          cohortPct === null
            ? null
            : { value: `${formatPct(cohortPct)} net of fees`, tone: cohortPct >= 0 ? "up" : "down" }
        }
        hint={
          <span className="tabular">
            <span className="text-up">{tracking}</span> tracking
            <span className="px-1 text-quiet">·</span>
            <span className={diverging > 0 ? "text-warn" : "text-quiet"}>{diverging}</span> diverging
          </span>
        }
      />

      {/* Tracks — how many cleared the Gate and run on live data. */}
      <MetricCard
        label="Tracks"
        tone="info"
        value={<span className="text-foreground">{total}</span>}
        hint="cleared the Gate · marked on live data"
      />

      {/* Live-ready — matured share past +30d net-positive, with the maturity gauge. */}
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
            <span className={cn("text-quiet")}>matured past +{LIVE_READY_DAYS}d net-positive</span>
          </div>
        }
      />
    </div>
  );
}
