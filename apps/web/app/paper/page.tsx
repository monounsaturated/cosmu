// /paper — the Paper dashboard (Iris Bento). Stage 3 of the lifecycle: strategies that cleared the Gate run
// here on REAL market bars with no real money. The surface mirrors the Live dashboard: an equity hero on
// top, then a 4-box KPI grid + capital-allocation donut, then [Open positions | Track record] side by side,
// and a footnote stating the allocated-not-pooled model + the fee assumptions.
//
// Loading UX: this is a SYNC server component that returns the toolbar chrome instantly and streams the data
// region via <Suspense>. PaperData does the awaits.
//
// HONESTY (+ NO POOLED WALLET): every number is real or an honest "—"/empty. The hero shows Σ per-strategy
// ALLOCATED capital + P&L (the /overview read-out, never the $100k sim_bankroll, never a venue's free
// paper-balance); the KPI/positions/donut read only marked dollar fields. "Track record" keeps CLOSED paper
// tracks (killed but once-traded) with their funded amount + final net-of-fee P&L — losses are remembered,
// not erased. NotConnected when the engine is unreachable; EmptyState only when there are neither active nor
// closed paper tracks. Nothing is fabricated.

import { Suspense } from "react";
import { engineConfigured, getLeaderboard, getOverview } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { EquityHero } from "@/components/live/equity-hero";
import { SimSummary } from "@/components/paper/sim-summary";
import { PaperPositions } from "@/components/paper/track-card";
import { WalletAllocCard } from "@/components/paper/wallet-alloc";
import { ClosedTracks } from "@/components/paper/closed-tracks";
import { StopPaperButton } from "@/components/paper/stop-paper-button";
import { isClosedPaperRow, isPaperRow } from "@/lib/utils";

export default function PaperPage() {
  return (
    <Page>
      <Toolbar title="Paper" right={<StopPaperButton />} />
      <Suspense fallback={<div className="skel" style={{ height: 360 }} />}>
        <PaperData />
      </Suspense>
    </Page>
  );
}

async function PaperData() {
  // Leaderboard drives the cohort (filtered to paper stage); /overview supplies the aggregate Paper equity
  // curve (Σ across all standalone paper tracks, net of fees) for the hero. Fetch both in parallel.
  const [{ leaderboard, connected }, { overview }] = await Promise.all([getLeaderboard(), getOverview()]);
  const allRows = leaderboard.rows as LeaderboardRow[];

  // Filter to paper-stage strategies (status = forward / forward_test / paper).
  // Paper cohort = strategies that have genuinely TRADED on paper (a real fill), not merely a paper-ish
  // status. A funded documented arm with zero fills is Backtest, so it never inflates the Paper dashboard
  // with fabricated value/P&L — the aggregate now tells the same story as each strategy's own sheet.
  const simRows = allRows.filter((r) => isPaperRow(r));
  // Closed paper tracks (killed AND once-traded) — their record survives the kill, shown in "Track record".
  const closedRows = allRows.filter((r) => isClosedPaperRow(r));

  if (!connected) {
    return (
      <NotConnected
        configured={engineConfigured}
        what="Strategies currently in paper appear here once the engine is connected. Each track runs on real bars with no real capital — the clock starts from Gate approval."
      />
    );
  }

  if (simRows.length === 0 && closedRows.length === 0) {
    return (
      <div className="card">
        <div className="card-body">
          <EmptyState
            title="No strategies in Paper yet."
            hint="Strategies move here automatically once they clear the Gate in Backtest. The Gate decides — you don’t move them manually."
          />
        </div>
      </div>
    );
  }

  return (
    // id="dash-paper" scopes the compact dashboard KPI sizing (globals.css #dash-paper .kpi-val/.kpi-box).
    <div id="dash-paper">
      {/* Equity hero ALWAYS on top — the real aggregate paper curve (Σ of all funded tracks, net of fees). */}
      <EquityHero label="Paper equity" curve={overview.equity_curve} />

      {/* Stats (2×2 KPI grid, left) + Capital allocation donut (right). */}
      <div className="kgrid dash-split" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
        <SimSummary rows={simRows} />
        <WalletAllocCard rows={simRows} />
      </div>

      {/* Open positions (active, left) + Track record (closed paper tracks, right). */}
      <div className="kgrid dash-split" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
        <PaperPositions rows={simRows} />
        <ClosedTracks rows={closedRows} />
      </div>

      {/* Honest read of the model: per-strategy allocated capital (NO pooled wallet, no venue free-balance),
          net of the gate's real per-venue fee + slippage assumptions. The venue's own paper-account size is
          irrelevant — only what each strategy deploys is shown. */}
      <p className="quiet" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.5 }}>
        Paper equity = Σ per-strategy <strong>allocated</strong> capital (each track funds itself, default $1,000)
        + P&amp;L — never a pooled wallet or a venue&apos;s free paper-balance. All returns are <strong>net of
        modeled fees &amp; slippage</strong> (the same per-venue cost model the Gate priced the edge against; see
        each strategy&apos;s sheet for its assumptions). Closed tracks keep their record above.
      </p>
    </div>
  );
}
