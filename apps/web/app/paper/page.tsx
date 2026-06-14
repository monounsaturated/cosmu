// /paper — the Paper dashboard (Iris Bento). Stage 3 of the lifecycle: strategies that cleared the Gate run
// here on REAL market bars with no real money. The surface mirrors the Live dashboard: an equity hero on
// top, then a 4-box KPI grid, then [Open positions | Recent trades] side by side.
//
// Loading UX: this is a SYNC server component that returns the toolbar chrome instantly and streams the data
// region via <Suspense>. PaperData does the awaits.
//
// HONESTY: every number is real or an honest "—"/empty. The hero is fed the engine's real aggregate paper
// equity curve (Σ across funded tracks, net of fees); the KPI/positions read only marked dollar fields; the
// trades card is an honest empty (no aggregate fill feed). NotConnected when the engine is unreachable,
// EmptyState when connected-but-no-paper-strategies. Nothing is fabricated.

import { Suspense } from "react";
import { engineConfigured, getLeaderboard, getOverview } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { EquityHero } from "@/components/live/equity-hero";
import { SimSummary } from "@/components/paper/sim-summary";
import { PaperPositions } from "@/components/paper/track-card";
import { WalletAllocCard } from "@/components/paper/wallet-alloc";
import { StopPaperButton } from "@/components/paper/stop-paper-button";
import { isPaper } from "@/lib/utils";

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
  const simRows = allRows.filter((r) => isPaper(r.status));

  if (!connected) {
    return (
      <NotConnected
        configured={engineConfigured}
        what="Strategies currently in paper appear here once the engine is connected. Each track runs on real bars with no real capital — the clock starts from Gate approval."
      />
    );
  }

  if (simRows.length === 0) {
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

      {/* 4-box KPI grid: Invested / P&L / Strategies / Live-ready. */}
      <SimSummary rows={simRows} />

      {/* [Open positions | Capital allocation donut] side by side — the donut replaces the honest-empty
          aggregate trades box (no cohort fill feed exists) with the wallet's real per-strategy split. */}
      <div className="kgrid dash-split" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <PaperPositions rows={simRows} />
        <WalletAllocCard rows={simRows} />
      </div>
    </div>
  );
}
