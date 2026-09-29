import type { ReactNode } from "react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { cn, formatPct, formatUsd, numOrNull } from "@/lib/utils";

// The Paper cohort KPI strip (Iris Bento `.kpi-grid`, mirrors the mockup's kpiPaper/kbox). Four honest,
// money-first read-outs over the REAL tracks the Gate has funded — it sits between the equity hero and the
// positions/trades split:
//   - Invested:    Σ deployed capital across paper tracks (current value − net P&L, per track).
//   - P&L:         Σ net-of-fee P&L in $ across marked tracks, with the cohort % in the sub-line.
//   - Strategies:  how many cleared the Gate and are now marked on live data.
//   - Live-ready:  how many crossed the +30-day net-positive threshold (live_ready === true).
//
// HONESTY: every number is derived from the rows the engine returned. The $ aggregates are summed ONLY over
// tracks that carry a real value_usd / pnl_usd — a cohort with no marked dollar history renders a plain "—"
// in a `.quiet` span, never a fabricated 0. The divergence split rides in the P&L sub-line.
const LIVE_READY_DAYS = 30;

// A finite-number guard (the shared honest-"—" helper) — null / NaN / non-finite never enters an aggregate.
const num = numOrNull;

// One bento KPI box. `cls` tones the value (up / gold / dn); the sub-line falls back to muted.
function KBox({ label, value, sub, cls }: { label: string; value: ReactNode; sub: ReactNode; cls?: string }) {
  return (
    <div className="kpi-box">
      <div className="kpi-label">{label}</div>
      <div className={cn("kpi-val tab", cls)}>{value}</div>
      <div className={cn("kpi-sub", cls ?? "muted")}>{sub}</div>
    </div>
  );
}

export function SimSummary({ rows }: { rows: LeaderboardRow[] }) {
  const total = rows.length;
  const matured = rows.filter((r) => r.live_ready).length;
  const tracking = rows.filter((r) => r.divergence_status === "tracking").length;
  const diverging = rows.filter((r) => r.divergence_status === "diverging").length;

  // Σ over tracks that carry REAL dollar marks. A track with null pnl_usd is excluded from the sum (never
  // counted as a fabricated 0). If no track carries a dollar mark, the aggregate is null → "—".
  const pnls = rows.map((r) => num(r.pnl_usd)).filter((v): v is number => v !== null);
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

  const pnlTone = totalPnl === null ? undefined : totalPnl > 0 ? "up" : totalPnl < 0 ? "dn" : undefined;

  return (
    <div className="kpi-grid">
      {/* Invested — Σ deployed capital across paper tracks (always $; "—" when nothing marked). */}
      <KBox
        label="Invested"
        value={invested === null ? <span className="quiet">—</span> : formatUsd(invested)}
        sub={
          invested === null
            ? "no marked track value yet"
            : `across ${investedParts.length} marked track${investedParts.length === 1 ? "" : "s"}`
        }
      />

      {/* P&L — Σ net-of-fee dollar P&L with the cohort % inline; the tracking/diverging health split in the sub. */}
      <KBox
        label="P&L"
        cls={pnlTone}
        value={
          totalPnl === null ? (
            <span className="quiet">—</span>
          ) : (
            <>
              {formatUsd(totalPnl)}
              {cohortPct !== null ? <span className="kpi-pct">{formatPct(cohortPct)}</span> : null}
            </>
          )
        }
        sub={
          <span className="tab">
            <span className="up">{tracking}</span> tracking
            <span className="quiet"> · </span>
            <span className={diverging > 0 ? "gold" : "quiet"}>{diverging}</span> diverging
            <span className="quiet"> · net of fees</span>
          </span>
        }
      />

      {/* Strategies — how many cleared the Gate and run on live data. */}
      <KBox label="Strategies" value={total} sub="cleared the Gate · running" />

      {/* Live-ready — matured share past +30d net-positive. */}
      <KBox
        label="Live-ready"
        cls={matured > 0 ? "gold" : undefined}
        value={
          <>
            {matured}
            <span className="quiet" style={{ fontSize: 13, fontWeight: 400 }}> / {total}</span>
          </>
        }
        sub={`≥ ${LIVE_READY_DAYS} net-positive days`}
      />
    </div>
  );
}
