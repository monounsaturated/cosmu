// Strategies — the v18 "Iris Bento" landing surface (mockup id=page-strategies). It answers ONE question:
// which Versions deserve my attention/capital, on what edge? Every Version runs on its own standalone track,
// ranked by risk-adjusted % (deflated OOS Sharpe). The page leads with the live MONEY-SPLIT `.summary-ribbon`
// + the population shape, then the sortable/column-pickable bento screener; rows open the per-Version sheet.
//
// LOADING UX: a SYNC server component returns the instant chrome (Page + Toolbar) and streams the data
// region under <Suspense> so the toolbar paints immediately while the engine read resolves.

import { Suspense } from "react";
import type { LeaderboardRow, PortfolioSummaryResponse } from "@cosmu/contracts-ts";
import { engineConfigured, getLeaderboard, getRealtimeStatus } from "../data";
// getPortfolioSummary is ambiguous through the barrel — import it from its canonical module to bind the
// live MONEY SPLIT into the ribbon.
import { getPortfolioSummary } from "../data/portfolio";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { RealtimeBadge } from "@/components/strategies/realtime-badge";
import { PopulationStrip } from "@/components/strategies/population-strip";
import { StrategiesTable } from "@/components/research/strategies-table";
import { cn, formatPct, formatUsd } from "@/lib/utils";

// Always render on-demand with fresh engine data — never statically pre-render (the engine may be offline
// at build time; on-demand lets the honest not-connected state handle it).
export const dynamic = "force-dynamic";

export default function StrategiesPage() {
  return (
    <Page>
      <Toolbar title="Strategies" />
      <Suspense fallback={<div className="skel" style={{ height: 420 }} />}>
        <StrategiesData />
      </Suspense>
    </Page>
  );
}

async function StrategiesData() {
  const [{ leaderboard, connected }, { realtime }, { summary }] = await Promise.all([
    getLeaderboard(),
    getRealtimeStatus(),
    getPortfolioSummary()
  ]);
  const rows = leaderboard.rows as LeaderboardRow[];

  if (!connected) {
    return (
      <NotConnected
        configured={engineConfigured}
        what="Every Version is judged in net-of-fee % on its own track — no pooled wallet. The faceted, ranked screener appears here once the engine is connected — no demo rows."
      />
    );
  }

  if (rows.length === 0) {
    return (
      <div className="card">
        <div className="card-body">
          <EmptyState
            title="No Versions yet — the Lab hasn't produced any."
            hint="Once the Lab authors a batch (or you drop an idea in the inbox) and Versions reach Paper, they show up here grouped by stage."
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <RealtimeBadge realtime={realtime} />
      </div>
      <SummaryRibbon summary={summary} rows={rows} />
      <PopulationStrip rows={rows} />
      <div className="card">
        <div className="card-body">
          <StrategiesTable rows={rows} />
        </div>
      </div>
    </div>
  );
}

// The v18 `.summary-ribbon` — a calm, dense strip that surfaces the LIVE money split (real capital, real
// P&L) the population counts do NOT carry. HONEST: when no Version is live (has_live false, the engine
// default) it says so plainly; null money fields render an explicit "—", never 0. The derived live % is
// shown only when BOTH the equity and the net P&L are real — never fabricated. Live is NEVER conflated with
// sim.
function SummaryRibbon({ summary, rows }: { summary: PortfolioSummaryResponse; rows: LeaderboardRow[] }) {
  const liveEquity = numOrNull(summary.live_equity);
  const livePnl = numOrNull(summary.live_pnl_net);
  const basis = liveEquity !== null && livePnl !== null ? liveEquity - livePnl : null;
  const livePct = basis && basis > 0 && livePnl !== null ? (livePnl / basis) * 100 : null;

  const paperRows = rows.filter((r) => isPaper(r.status));
  const bestPaper = paperRows.reduce<number | null>((best, r) => {
    const v = numOrNull(r.paper_return_pct);
    if (v === null) return best;
    return best === null || v > best ? v : best;
  }, null);

  return (
    <div className="summary-ribbon">
      {summary.has_live && liveEquity !== null ? (
        <>
          <div className="ribbon-item">
            <span className="ribbon-label" style={{ color: "var(--gold)" }}>LIVE</span>
            <span className="ribbon-val tab">{formatUsd(liveEquity)}</span>
          </div>
          <div className="ribbon-item">
            <span className="ribbon-label">P&amp;L</span>
            {livePnl === null ? (
              <span className="ribbon-val quiet">—</span>
            ) : (
              <span className={cn("ribbon-val tab", livePnl > 0 ? "up" : livePnl < 0 ? "dn" : "")} style={{ fontWeight: 700 }}>
                {signedUsd(livePnl)}
                {livePct !== null ? ` (${formatPct(livePct, 0)})` : ""}
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="ribbon-item">
          <span className="ribbon-label">Live</span>
          <span className="ribbon-val quiet">No Version live — sim only</span>
        </div>
      )}

      <div className="ribbon-sep" />

      <div className="ribbon-item" style={{ opacity: 0.6 }}>
        <span className="ribbon-label">Best paper</span>
        {bestPaper === null ? (
          <span className="ribbon-val quiet">—</span>
        ) : (
          <span className={cn("ribbon-val tab", bestPaper >= 0 ? "up" : "dn")}>{formatPct(bestPaper, 2)}</span>
        )}
      </div>

      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16 }}>
        <div className="ribbon-item">
          <span className="ribbon-label">Live</span>
          <span className="ribbon-val tab">{summary.positions_count_live}</span>
        </div>
        <div className="ribbon-item">
          <span className="ribbon-label">Paper</span>
          <span className="ribbon-val tab">{paperRows.length}</span>
        </div>
      </div>
    </div>
  );
}

function numOrNull(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function signedUsd(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}${formatUsd(Math.abs(v))}`;
}

function isPaper(status: string | null | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "paper" || s === "forward_test" || s === "forward";
}
