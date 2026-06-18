// Strategy detail — the DEFINITIVE inspect view for one Version, redrawn in v18 "Iris Bento" as the SAME
// focused sheet the screener shows in its side panel, rendered as a full bento page: a title block, then
// the shared StrategySheet (stage control + money band + equity + AI summary + phase comparison + gate
// chips + building blocks + trade blotter + activity), then the full Spec/code/notes/holdout a tap away.
// All from the existing strategy-detail endpoint — nothing fabricated; honest empty states throughout.
//
// LOADING UX: a SYNC server component returns the instant chrome (Page + Toolbar) and streams the data
// region under <Suspense>.

import { Suspense } from "react";
import type { Backtest } from "@cosmu/contracts-ts";
import { engineConfigured, getStrategy } from "../../data";
import { getComparison, getTriplet } from "../../data/lab";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { StrategyHeader } from "@/components/strategies/strategy-header";
import { StrategySheet, bestOosPct } from "@/components/strategy/strategy-sheet";
import { SpecView } from "@/components/strategy/spec-view";
import { GateChips } from "@/components/strategy/gate-chips";
import { TripletCard } from "@/components/strategy/triplet-card";
import { SymbolsTable } from "@/components/lab/symbols-table";

export const dynamic = "force-dynamic";

export default async function StrategyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ symbol?: string; venue?: string }>;
}) {
  const { id } = await params;
  const { symbol, venue } = await searchParams;
  return (
    <Page>
      <Toolbar title="Version" />
      <Suspense fallback={<div className="skel" style={{ height: 460 }} />}>
        <StrategyDetail id={id} symbol={symbol} venue={venue} />
      </Suspense>
    </Page>
  );
}

async function StrategyDetail({ id, symbol, venue }: { id: string; symbol?: string; venue?: string }) {
  // The version sheet AND the triplet view share this one Version. The triplet card focuses the clicked
  // (symbol, venue) cell; the comparison grid is the WHOLE algo across assets/venues. All from the engine —
  // honest empties when a strategy has no per-symbol cells yet.
  const [{ strategy, connected }, { data: triplet }, { data: comparison }] = await Promise.all([
    getStrategy(id),
    getTriplet(id, symbol, venue),
    getComparison(id),
  ]);

  if (!connected || !strategy.version_id) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h1 className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--fg)", margin: 0 }}>{id}</h1>
        <NotConnected
          configured={engineConfigured}
          what="This Version's full picture — spec, compiled code, trade blotter, OOS/holdout evidence, and the agent summary — comes from the live engine. Nothing is fabricated."
        />
      </div>
    );
  }

  // The contract declares backtests/holdout non-null, but the engine can omit them. Normalize once so no
  // `.some`/`.map`/Object.entries below can throw on a partial response and white-screen the page.
  const backtests = strategy.backtests ?? [];
  const holdout = strategy.holdout ?? {};
  const passed = backtests.some((bt: Backtest) => bt.passed_gates);
  const summaryLane = strategyLane(strategy.spec ?? {});
  const bestOos = bestOosPct(backtests);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1000 }}>
      <StrategyHeader
        name={strategy.name}
        versionId={strategy.version_id}
        passed={passed}
        lane={[summaryLane.venue, summaryLane.timeframe]}
        thesis={summaryLane.thesis}
        bestOos={bestOos}
      />

      {/* The triplet header — the clicked (algo × asset × venue) cell + the asset/venue selector that
          navigates to a sibling triplet. Only shown when this algo has per-symbol cells. */}
      {comparison.rows.length > 0 ? (
        <TripletCard cell={triplet.cell} comparison={comparison.rows} />
      ) : null}

      {/* The shared sheet body — identical to the screener's side panel. When a triplet cell is focused (the
          page was opened from a clicked cell), the backtest-phase headline reads that cell's STANDALONE truth
          (Return / Max DD / Trades + equity), not the pooled `backtests` aggregate — the brut-combo garbage fix. */}
      <StrategySheet strategy={strategy} cell={triplet.cell} />

      {/* Per-backtest Gate detail + the full spec/code/notes/holdout, given room on the standalone page. */}
      <GateTab backtests={backtests} holdout={holdout} />

      <div className="card">
        <div className="card-hdr">
          <span className="card-lbl">Spec</span>
        </div>
        <div className="card-body">
          <SpecView spec={strategy.spec} params={strategy.params} />
        </div>
      </div>

      <div className="card">
        <div className="card-hdr">
          <span className="card-lbl">Compiled code</span>
        </div>
        <div className="card-body">
          {strategy.generated_code ? (
            <pre className="mono iris" style={{ maxHeight: 420, overflow: "auto", fontSize: 12, lineHeight: 1.5, margin: 0 }}>
              {strategy.generated_code}
            </pre>
          ) : (
            <EmptyState title="No compiled code." hint="The compiled artifact appears here once this Version's spec has been compiled." />
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-hdr">
          <span className="card-lbl">Agent notes</span>
        </div>
        <div className="card-body">
          {strategy.notes_md ? (
            <div className="ai-body" style={{ whiteSpace: "pre-wrap" }}>{strategy.notes_md}</div>
          ) : (
            <EmptyState title="No notes recorded." hint="The agent's rationale and post-mortem for this Version appear here when present." />
          )}
        </div>
      </div>

      {/* Comparison — this algo across every asset & venue, one row per triplet, never pooled. The clicked
          cell is highlighted; a row opens its own fiche. Same SymbolsTable the merged Strategies surface uses. */}
      {comparison.rows.length > 0 ? (
        <div className="card">
          <div className="card-hdr">
            <span className="card-lbl" data-tip="Every (asset × venue) cell of THIS algo — each with its own P&L/verdict. Nothing averaged. Click a cell to open its fiche.">
              Comparison · {comparison.rows.length}
            </span>
          </div>
          <div className="card-body">
            <SymbolsTable
              rows={comparison.rows}
              symbols={comparison.symbols}
              venues={comparison.venues}
              title="Comparison"
              caption={false}
              navigateOnClick
              highlight={triplet.cell ? { strategy_version_id: triplet.cell.strategy_version_id, symbol: triplet.cell.symbol, venue_id: triplet.cell.venue_id } : undefined}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── Per-backtest Gate detail + the untouched holdout, in bento cards. ──
function GateTab({ backtests, holdout }: { backtests: Backtest[] | null | undefined; holdout: Record<string, unknown> | null | undefined }) {
  const bts = backtests ?? [];
  const holdoutRows = Object.entries(holdout ?? {}).map(([k, v]) => {
    const label = k.replace(/_/g, " ");
    if (typeof v === "boolean") return { label, value: v ? "yes" : "no", tone: v ? "up" : "dn" };
    if (typeof v === "number") return { label, value: v.toFixed(2), tone: "" };
    return { label, value: String(v), tone: "" };
  });

  return (
    <div className="card">
      <div className="card-hdr">
        <span className="card-lbl" data-tip="Each backtest's deterministic verdict, plus the one-shot untouched holdout that gates promotion.">
          Gate · {bts.length}
        </span>
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {bts.length === 0 ? (
          <EmptyState title="No backtests yet." hint="Gate verdicts appear here once this Version has been backtested." />
        ) : (
          bts.map((bt) => (
            <div key={bt.id} className="psec" style={{ margin: 0 }}>
              <div className="psec-title with-btn">
                <span style={{ textTransform: "uppercase" }}>{bt.kind}</span>
                <span className={bt.passed_gates ? "badge badge-up" : "badge badge-dn"}>{bt.passed_gates ? "passed" : "blocked"}</span>
              </div>
              <GateChips backtest={bt} />
              <div className="blocks" style={{ marginTop: 8 }}>
                <div className="block-row">
                  <span className="block-key">Trades</span>
                  <span className="block-val">
                    {bt.num_trades} · win {(bt.win_rate * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
          ))
        )}

        <div className="psec" style={{ margin: 0 }}>
          <div className="psec-title" data-tip="The one-shot, seen-once test. A Version may only meet its holdout once — passing it is what allows promotion.">
            Untouched holdout
          </div>
          {holdoutRows.length ? (
            <div className="blocks">
              {holdoutRows.map((r) => (
                <div key={r.label} className="block-row">
                  <span className="block-key" style={{ width: 120, textTransform: "capitalize" }}>{r.label}</span>
                  <span className={`block-val ${r.tone}`}>{r.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="quiet" style={{ fontSize: 11 }}>No holdout recorded — this Version has not met its untouched holdout yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// Pull the lane/thesis off the REAL spec fields, defensively.
function strategyLane(spec: Record<string, unknown>): { thesis: string | null; venue: string | null; timeframe: string | null } {
  const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
  const universe = isRecord(spec.universe) ? spec.universe : null;
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const venues = universe && Array.isArray(universe.venues) ? (universe.venues as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const tfRaw = horizon && typeof horizon.timeframe === "string" ? horizon.timeframe : null;
  return {
    thesis: typeof spec.rationale === "string" && spec.rationale ? spec.rationale : null,
    venue: venues.length ? venues.join(" · ") : null,
    timeframe: tfRaw
  };
}
