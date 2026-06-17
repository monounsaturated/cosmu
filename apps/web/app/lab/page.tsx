// Lab — per-symbol backtest performance. The pooled leaderboard answers "which Version has edge?"; this answers
// the question the operator insisted on: "how does each strategy do on EACH symbol (and each venue), not pooled?"
// One row per (strategy × symbol × venue), outlier-ranked so the strongest standalone result leads, each carrying
// the honest cross-symbol VERDICT (robust / fragile / thin / negative) so a lone best-of-N winner is flagged with
// caution, never celebrated as proven. The deterministic Gate still decides funding — this is pure visibility.
//
// LOADING UX: a sync server component returns the chrome (Page + Toolbar) and streams the data region under
// <Suspense> so the toolbar paints immediately while the engine read resolves.

import { Suspense } from "react";
import { engineConfigured } from "../data";
import { getLabSymbols } from "../data/lab";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { SymbolsTable } from "@/components/lab/symbols-table";

export const dynamic = "force-dynamic";

export default function LabPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Lab" />
            <div className="skel" style={{ height: 420 }} />
          </>
        }
      >
        <LabData />
      </Suspense>
    </Page>
  );
}

async function LabData() {
  const { data, connected } = await getLabSymbols();

  if (!connected) {
    return (
      <>
        <Toolbar title="Lab" />
        <NotConnected
          configured={engineConfigured}
          what="Per-symbol backtest performance — every strategy × symbol × venue, ranked by outlier, each with an honest robust/fragile verdict so a lone best-of-N winner is flagged. Appears once the engine is connected — no demo rows."
        />
      </>
    );
  }

  if (data.rows.length === 0) {
    return (
      <>
        <Toolbar title="Lab" />
        <div className="card">
          <div className="card-body">
            <EmptyState
              title="No per-symbol results yet."
              hint="Run the Strategy Finder (or wait for the autonomous discovery tick) — every backtest writes one row per symbol here, outlier-ranked and verdict-labelled."
            />
          </div>
        </div>
      </>
    );
  }

  return <SymbolsTable rows={data.rows} symbols={data.symbols} venues={data.venues} />;
}
