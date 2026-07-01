// Strategies — the v18 "Iris Bento" landing surface, now the ONE GRANULAR surface (the old per-symbol Lab is
// folded in here). It answers the question the operator insisted on: how does each strategy do on EACH symbol
// and EACH venue — never a pooled mean? Every row is one (algo × asset × venue) triplet, outlier-ranked and
// verdict-labelled; the parent backtest's pooled number rides along as advisory only. The page leads with the
// live MONEY-SPLIT `.summary-ribbon`, then the sortable/filterable triplet grid; a row opens its triplet fiche.
//
// LOADING UX: a SYNC server component returns the instant chrome (Page + Toolbar) and streams the data
// region under <Suspense> so the toolbar paints immediately while the engine read resolves.

import { Suspense } from "react";
import type { LeaderboardRow, PortfolioSummaryResponse } from "@cosmu/contracts-ts";
import { engineConfigured, getLeaderboard } from "../data";
import { getLabSymbols } from "../data/lab";
// getPortfolioSummary is ambiguous through the barrel — import it from its canonical module to bind the
// live MONEY SPLIT into the ribbon.
import { getPortfolioSummary } from "../data/portfolio";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { SymbolsTable } from "@/components/lab/symbols-table";
import { cn, formatPct, formatUsd, isPaperRow, numOrNull, signedUsd } from "@/lib/utils";

// Always render on-demand with fresh engine data — never statically pre-render (the engine may be offline
// at build time; on-demand lets the honest not-connected state handle it).
export const dynamic = "force-dynamic";

export default function StrategiesPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Bots" />
            <div className="skel" style={{ height: 420 }} />
          </>
        }
      >
        <StrategiesData />
      </Suspense>
    </Page>
  );
}

async function StrategiesData() {
  // The triplet grid is the surface; the leaderboard + portfolio summary feed ONLY the money-split ribbon
  // (live equity / P&L / paper count) — an overview, not a competing table.
  const [{ data: lab, connected }, { leaderboard }, { summary }] = await Promise.all([
    getLabSymbols(),
    getLeaderboard(),
    getPortfolioSummary(),
  ]);
  const rows = leaderboard.rows as LeaderboardRow[];

  if (!connected) {
    return (
      <>
        <Toolbar title="Bots" />
        <NotConnected
          configured={engineConfigured}
          what="Every strategy is shown at the (algo × asset × venue) triplet — one row per cell, never a pooled mean. Each carries an honest robust/fragile verdict; the pooled number is advisory only. Appears once the engine is connected — no demo rows."
        />
      </>
    );
  }

  if (lab.rows.length === 0) {
    return (
      <>
        <Toolbar title="Bots" />
        <div className="card">
          <div className="card-body">
            <EmptyState
              title="No per-symbol results yet."
              hint="Once the Lab backtests a strategy (or the autonomous discovery tick runs), every (symbol × venue) cell shows up here — outlier-ranked, verdict-labelled, each with its own P&L. The deterministic Gate alone decides funding."
            />
          </div>
        </div>
      </>
    );
  }

  // Population counts for the ribbon, derived from the SAME lab rows the screener numbers (no extra fetch):
  //   • strategyCount = distinct ALGORITHMS (strategy_name) — matches the screener's "#N" algorithm map.
  //   • comboCount    = distinct COMBOS (the algo × symbol × venue triplet) — matches the "#N" combo map.
  // The triplet key mirrors symbols-table's comboKeyOf (venue normalised to "" so a NULL-venue cell has one key).
  // LOADED count (numerator) vs the engine's TRUE totals over the WHOLE set (denominators), so the ribbon shows an
  // honest "loaded of total" rather than passing off the page `limit` as the universe. strategyCount uses the
  // engine total (fixes the old top-1000 slice); falls back to the loaded distinct count when the engine omits it.
  const strategyCount = lab.total_strategies && lab.total_strategies > 0 ? lab.total_strategies : new Set(lab.rows.map((r) => r.strategy_name)).size;
  const loadedCombos = new Set(lab.rows.map((r) =>`${r.strategy_version_id} ${r.symbol} ${r.venue_id ?? ""}`)).size;

  // The one granular surface: the live money-split ribbon, then the (algo × asset × venue) triplet grid (its
  // own toolbar-row + table). A row opens its triplet fiche. Reuses the same SymbolsTable the fiche's
  // comparison grid renders, so the granular truth is shown ONE way everywhere.
  // True combo denominator over the WHOLE set (engine total), falling back to the loaded distinct count when the
  // engine omits it — so the ribbon reads an honest "loaded of total".
  const totalCombos = lab.total_combos && lab.total_combos > 0 ? lab.total_combos : loadedCombos;

  return (
    <SymbolsTable
      rows={lab.rows}
      symbols={lab.symbols}
      venues={lab.venues}
      timeframes={lab.timeframes}
      minTrades={lab.min_trades}
      title="Bots"
      totalCombos={totalCombos}
      ribbon={<SummaryRibbon summary={summary} rows={rows} strategyCount={strategyCount} loadedCombos={loadedCombos} totalCombos={totalCombos} />}
    />
  );
}

// The v18 `.summary-ribbon` — a calm, dense strip that surfaces the LIVE money split (real capital, real
// P&L) the population counts do NOT carry. HONEST: when no Version is live (has_live false, the engine
// default) it says so plainly; null money fields render an explicit "—", never 0. The derived live % is
// shown only when BOTH the equity and the net P&L are real — never fabricated. Live is NEVER conflated with
// sim.
function SummaryRibbon({
  summary,
  rows,
  strategyCount,
  loadedCombos,
  totalCombos,
}: {
  summary: PortfolioSummaryResponse;
  rows: LeaderboardRow[];
  strategyCount: number;
  loadedCombos: number; // distinct combos in the loaded rows — the numerator ("loaded of total")
  totalCombos: number; // the engine's TRUE distinct-combo total over the whole set — the honest denominator
}) {
  const liveEquity = numOrNull(summary.live_equity);
  const livePnl = numOrNull(summary.live_pnl_net);
  const basis = liveEquity !== null && livePnl !== null ? liveEquity - livePnl : null;
  const livePct = basis && basis > 0 && livePnl !== null ? (livePnl / basis) * 100 : null;

  const paperRows = rows.filter((r) => isPaperRow(r));
  // The honest "Bots trading" count: a Bot = a combo (algo × asset × venue) that ACTUALLY trades — paper with a
  // real fill (isPaperRow) OR live. Every other combo on the screener is a backtest, not a trading bot. This is
  // the sub-count that keeps "1,000 of 36,065 bots" from implying all 36,065 trade.
  const botsTrading = rows.filter((r) => isPaperRow(r) || (r.status ?? "").toLowerCase() === "live").length;
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
          <span className="ribbon-val quiet">No Version live — paper only</span>
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
        {/* Counters, left→right: Bots · Trading · Strategies · Live. "Bots" renames the old "Combos" and shows the
            TRUE denominator ("1,000 of 36,065") — the old number was just the page cap. "Trading" is the honest
            sub-count (how many of those bots actually trade). A Bot = a combo (algo × asset × venue); only a
            combo that trades (paper-with-fills or live) is a live/paper bot — the rest are backtests. */}
        <div className="ribbon-item">
          <span className="ribbon-label" data-tip="A Bot is a combo (algo × asset × venue). The screener lists every BACKTESTED combo; this shows how many are loaded on the page of the true total. Only the 'Trading' subset actually trades.">Bots</span>
          {/* Fixed 'en-US' grouping — a bare toLocaleString() uses the runtime locale, which differs server (Node)
              vs client (browser) and triggers a React hydration mismatch ("1 000" vs "1,000"). */}
          <span className="ribbon-val tab">
            {loadedCombos.toLocaleString("en-US")}
            <span className="quiet"> of {totalCombos.toLocaleString("en-US")}</span>
          </span>
        </div>
        <div className="ribbon-item">
          <span className="ribbon-label" data-tip="Bots that have ACTUALLY traded — paper with real fills, or live (matches the grid's 'Paper'/'Live' badges). Every other combo on the screener is a backtest. These funded survivors are monthly equity-TAA (DAA · VAA · ADM · GTAA …): they rebalance roughly once a month, so they hold and book no new fills most days. Idle ≠ broken; nothing is armed live by design (a human clicks launch).">Trading</span>
          <span className="ribbon-val tab">{botsTrading.toLocaleString("en-US")}</span>
        </div>
        <div className="ribbon-item">
          <span className="ribbon-label" data-tip="Distinct strategies (algorithms) with a backtested cell — over the WHOLE set, not the loaded page.">Strategies</span>
          <span className="ribbon-val tab">{strategyCount.toLocaleString("en-US")}</span>
        </div>
        <div className="ribbon-item">
          <span className="ribbon-label" style={{ color: summary.positions_count_live > 0 ? "var(--gold)" : undefined }} data-tip="Open LIVE positions — real money at the venue.">Live</span>
          <span className="ribbon-val tab" style={summary.positions_count_live > 0 ? { color: "var(--gold)", fontWeight: 700 } : undefined}>{summary.positions_count_live}</span>
        </div>
      </div>
    </div>
  );
}
