"use client";

// module: StrategySheet — the SHARED per-Version detail body, rendered identically inside the screener's
// right `SidePanel` and on the standalone `/strategy/[id]` bento page. It implements the approved "bot sheet"
// redesign (mockups/strat-sheet/final-c-v3.html) as the SECTION STRUCTURE only — every number is bound to a
// REAL field off StrategyDetailResponse, never the mockup's synthetic arrays.
//
// LAYOUT (C-v3):
//   1. ONE merged top card — title + Go-live/Stop (StageControl), status "Paper · N days", a small "Gated"
//      badge (derived from the real Gate verdict), a meta line (Quant/LLM badge → venue → Universe with
//      currently-HELD tickers tinted purple), then FOUR compact number boxes (Value · P&L with the % INLINE ·
//      Max drawdown · Fees). Invested is NOT a box — it lives in the Gate tab.
//   2. A card with the equity chart (short) + a Backtest/Paper toggle, then "What this does" below it.
//   3. A "Technical details" card with a tab bar: Trades (default) · Stats · Gate · Spec.
//
// HONESTY: every number is bound to a REAL field off StrategyDetailResponse. So:
//   • money-band → Value/P&L/Fees are the engine's MARKED forward money (latest scope='track' snapshot −
//     starting_capital, gated on a real paper fill) — the SAME source the leaderboard serves. All render "—"
//     until the track is marked; NEVER a fabricated loss from buy notionals.
//   • Max drawdown box → the strongest backtest's measured max_dd (the per-cell value when a cell is focused).
//   • equity → the engine's marked scope='track' equity trajectory (strategy.forward_equity); honest empty
//     when < 2 marked points.
//   • "What this does" → summary_md, else the spec's own rationale; honest "no summary yet" when null.
//   • Universe held tickers → spec.current_holdings (the real held set); no fabricated universe-but-not-held
//     symbols (the contract carries no universe symbol list, so we never invent dashed placeholders).
//   • Gated badge → the strongest backtest's passed_gates verdict; absent when no backtest ran.
//   • Trades tab → the real Execution blotter (no fabricated per-fill P&L; symbol per row is "—" because the
//     served Execution carries no symbol — never faked).
//   • Stats/Gate tabs → the strongest backtest's measured DSR/PBO/Max-DD/OOS/trades + the paper-vs-backtest
//     phase table; every cell with no real source (Sharpe-in-paper, the whole Live column, …) is an explicit "—".
//   • Spec tab → derived from the real spec (family / rule / rebalance / venue / universe / safety-leg).

import { useState } from "react";
import type { Backtest, Execution, LabSymbolRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { AiSummary } from "./ai-summary";
import { CostBasisSelector } from "./cost-basis-selector";
import { EquityPanel } from "./equity-panel";
import { SpecBlocks } from "./spec-view";
import { RegistryBlocks } from "./registry-blocks";
import { StageControl, type Stage } from "./stage-control";
import { LifecycleTrace } from "./lifecycle-trace";
import {
  bestOosPct,
  deriveStage,
  feeTotalFromTrades,
  formatOosWindow,
  headlineBacktest,
  holdoutVerdict,
  referencedFeatures,
  trackAgeDays
} from "./strategy-sheet-utils";
import { laneOf, provenanceOf, strategyKindOf } from "@/lib/provenance";
import { type Kind, KIND_LABEL, KIND_BADGE_CLASS } from "@/lib/lifecycle";
import { cn, fmtTz, formatUsd, formatVenue } from "@/lib/utils";

// The pure, server-safe derivations live in ./strategy-sheet-utils (this module is a Client Component, and a
// client module's exports can't be CALLED from the server page). Re-export the ones other client modules already
// import from here so their import paths keep working.
export { bestOosPct, bestOosAnnualizedPct, feeTotalFromTrades, holdoutVerdict, referencedFeatures } from "./strategy-sheet-utils";

// ── Honest derivations off the real detail response ──

// Gate reference (mirrors gate-chips): PBO must be under 0.50 to pass.
const PBO_CEILING = 0.5;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ── The currently-HELD tickers off the real spec — the engine records the live holding set on spec.current_holdings
// (a string[] the paper/live loop stamps as it rebalances). Sorted + de-duped + coerced defensively; [] → the
// Universe block renders nothing (no fabricated tickers). This is the ONLY served symbol set — the contract carries
// no full universe symbol list, so we never invent "universe-but-not-held" dashed placeholders. ──
function currentHoldings(spec: Record<string, unknown> | null | undefined): string[] {
  if (!spec || typeof spec !== "object") return [];
  const raw = (spec as Record<string, unknown>).current_holdings;
  if (!Array.isArray(raw)) return [];
  const out = new Set<string>();
  for (const s of raw) if (typeof s === "string" && s.trim()) out.add(s.trim());
  return [...out].sort();
}

// ── Venue · asset-class label off the real spec.universe ({asset_classes, venues}). "IBKR · equity"-style line
// for the meta row + the Spec tab. null when nothing is recorded. ──
function venueLabel(spec: Record<string, unknown> | null | undefined): string | null {
  if (!spec) return null;
  const universe = isRecord(spec.universe) ? spec.universe : null;
  if (!universe) return null;
  const venues = Array.isArray(universe.venues) ? (universe.venues as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const classes = Array.isArray(universe.asset_classes) ? (universe.asset_classes as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const venueStr = venues.length ? venues.map((v) => formatVenue(v)).join(" · ") : null;
  const classStr = classes.length ? classes.join(" · ") : null;
  if (venueStr && classStr) return `${venueStr} · ${classStr}`;
  return venueStr ?? classStr ?? null;
}

// ── The merged top card: title (StageControl carries Go-live/Stop + status + the Gated badge), the meta line
// (Quant/LLM badge → venue → Universe held-purple), and the four compact number boxes. ──
function TopCard({
  strategy,
  stage,
  ageDays,
  headlineBt,
  cell,
  paperPnl,
  paperPnlPct,
  totalFee,
  holdings
}: {
  strategy: StrategyDetailResponse;
  stage: Stage;
  ageDays: number | null;
  headlineBt: Backtest | null;
  cell?: LabSymbolRow | null;
  paperPnl: number | null;
  paperPnlPct: number | null;
  totalFee: number | null;
  holdings: string[];
}) {
  const spec = (strategy.spec ?? {}) as Record<string, unknown>;
  const mk: Kind = strategy.kind === "llm" ? "llm" : "quant";
  const venue = venueLabel(spec);
  // "Gated" = the strongest backtest cleared the deterministic Gate. Absent when no backtest has run.
  const gated = Boolean(headlineBt?.passed_gates);

  // Max-drawdown box — the per-cell value when a cell is focused, else the headline backtest's (fractions → %).
  const maxDdPct = cell ? cell.max_drawdown * 100 : headlineBt ? headlineBt.max_dd * 100 : null;

  // P&L box — the % INLINE next to the dollar amount on the SAME line (C-v3 spec). Neutral at exactly $0.
  const pnlClass = paperPnl === null || paperPnl === 0 ? "" : paperPnl > 0 ? "up" : "dn";
  const pnlDollar =
    paperPnl === null
      ? "—"
      : paperPnl === 0
        ? formatUsd(0, 2)
        : `${paperPnl > 0 ? "+" : "-"}${formatUsd(Math.abs(paperPnl), 2)}`;
  const pnlPctStr =
    paperPnlPct === null
      ? null
      : paperPnlPct === 0
        ? "0.0%"
        : `${paperPnlPct > 0 ? "+" : "-"}${Math.abs(paperPnlPct).toFixed(1)}%`;

  return (
    <div className="sheet-card">
      <StageControl
        stage={stage}
        ageDays={ageDays}
        strategyName={strategy.name}
        versionId={strategy.version_id}
        goLiveEligible={stage === "paper" || Boolean(headlineBt?.passed_gates)}
        gated={gated}
      />

      {/* meta line: Quant/LLM badge FIRST, then venue. The Universe (held-purple) sits below it. */}
      <div className="sheet-meta">
        <span
          className={KIND_BADGE_CLASS[mk]}
          data-tip={mk === "llm" ? "Agentic / natural-language strategy (AgentSpec)." : "Typed StrategySpec routed through the deterministic Gate."}
        >
          {KIND_LABEL[mk]}
        </span>
        {venue ? <span className="sheet-venue">{venue}</span> : null}
      </div>

      {holdings.length ? (
        <div className="uni-block">
          <span className="uni-label" data-tip="The instruments this strategy is currently holding — the live positions the last rebalance set. Purple = held now.">Universe</span>
          {holdings.map((t) => (
            <span key={t} className="tick tick-held">{t}</span>
          ))}
        </div>
      ) : null}

      {/* Four COMPACT number boxes: Value · P&L (inline %) · Max drawdown · Fees. Invested is NOT here — it's
          in the Gate tab. Reuses the existing .money-band / .mb-cell chrome. */}
      <div className="money-band sheet-nums">
        <div className="mb-cell">
          <div className="mb-label">Value</div>
          <div className="mb-val">{strategy.value_usd != null ? formatUsd(strategy.value_usd, 2) : "—"}</div>
          <div className="mb-sub">{strategy.value_usd != null ? "marked now" : "not marked yet"}</div>
        </div>
        <div className="mb-cell">
          <div className="mb-label">P&amp;L</div>
          <div className={cn("mb-val", pnlClass)}>
            {pnlDollar}
            {pnlPctStr !== null ? <span className={cn("mb-pnl-pct", pnlClass)}> ({pnlPctStr})</span> : null}
          </div>
          <div className="mb-sub">
            {paperPnl == null ? "not marked yet" : ageDays !== null ? `${ageDays}d · realized + unrealized` : "realized + unrealized"}
          </div>
        </div>
        <div className="mb-cell">
          <div className="mb-label">Max drawdown</div>
          <div className="mb-val">{maxDdPct !== null ? `−${maxDdPct.toFixed(1)}%` : "—"}</div>
          <div className="mb-sub">{maxDdPct !== null ? "backtest worst drop" : "no backtest yet"}</div>
        </div>
        <div className="mb-cell">
          <div className="mb-label">Fees</div>
          <div className="mb-val">{totalFee != null ? formatUsd(totalFee, 2) : "—"}</div>
          <div className="mb-sub">{totalFee != null ? (stage === "paper" ? "off simulated fills" : "off real fills") : "no fills yet"}</div>
        </div>
      </div>
    </div>
  );
}

// "Jun 09 14:22" parts, split so the time reads quiet. Rendered in the operator's timezone (fmtTz) so a
// server-rendered blotter shows wall-clock Paris time, not the Vercel server's UTC.
function dateTimeParts(ts: string): { date: string; time: string } | null {
  if (Number.isNaN(new Date(ts).getTime())) return null;
  return {
    date: fmtTz(ts, { month: "short", day: "2-digit" }),
    time: fmtTz(ts, { hour: "2-digit", minute: "2-digit", hour12: false })
  };
}

// ── Trades tab — the real Execution blotter (newest first). Columns: Date · Side · Symbol · Price · Qty · Fee.
// The served Execution carries NO symbol, so the Symbol column reads an honest "—" (never a fabricated ticker).
// No per-fill P&L column: an opening BUY has $0 realized by definition and a close needs FIFO the blotter can't do. ──
function TradesPanel({ trades, stage }: { trades: Execution[]; stage: Stage }) {
  if (trades.length === 0) {
    return (
      <p className="quiet" style={{ fontSize: 11.5, padding: "6px 2px" }}>
        No fills yet — trades appear here as this track trades on live data. Nothing is fabricated.
      </p>
    );
  }
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  const sells = ordered.filter((t) => t.side === "sell").length;
  const sim = stage === "paper";
  return (
    <>
      <div className="tbl-scroll">
        <table className="mini-tbl">
          <thead>
            <tr>
              <th>Date</th>
              <th>Side</th>
              <th>Symbol</th>
              <th className="r">Price</th>
              <th className="r">Qty</th>
              <th className="r">Fee</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((t) => {
              const dt = dateTimeParts(t.ts);
              return (
                <tr key={t.id}>
                  <td>{dt ? <>{dt.date} <span className="quiet">{dt.time}</span></> : "—"}</td>
                  <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{t.side === "buy" ? "Buy" : "Sell"}</td>
                  {/* The served Execution carries no symbol — honest "—", never faked. */}
                  <td className="quiet">—</td>
                  <td className="r tab">{formatUsd(t.price, 2)}</td>
                  <td className="r tab">×{t.qty}</td>
                  <td className="r tab muted">{formatUsd(t.fee, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="quiet" style={{ fontSize: 11, margin: "10px 2px 0", lineHeight: 1.5 }}>
        {sells === 0
          ? "0 sells — the next rebalance window opens on the strategy's cadence."
          : `${sells} sell${sells === 1 ? "" : "s"} on the record.`}
        {sim ? " Paper fills are simulated against the venue's real fees; no real order is placed." : ""}
      </p>
    </>
  );
}

// Earliest fill timestamp (paper start) — for the Stats "Since" cell.
function sortedFirstTs(trades: Execution[]): string {
  return [...trades].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))[0]?.ts ?? "";
}

// ── Stats tab: paper-vs-backtest(OOS) metric table + a phase table (Backtest → Paper → Live) with the Live row
// filling after arming. PER-CELL TRUTH: when focused on ONE (algo × asset × venue) cell, Return / Max DD / Trades
// read the cell's STANDALONE backtest numbers, never the pooled aggregate (which for a brut-converted combo can
// carry garbage). Every cell with no real source ("Sharpe in paper", the whole Live column) is an explicit "—". ──
function StatsPanel({
  headlineBt,
  paperPnl,
  paperPnlPct,
  trades,
  ageDays,
  bestOos,
  cell,
  stage
}: {
  headlineBt: Backtest | null;
  paperPnl: number | null;
  paperPnlPct: number | null;
  trades: Execution[];
  ageDays: number | null;
  bestOos: number | null;
  cell?: LabSymbolRow | null;
  stage: Stage;
}) {
  const cellReturnPct = cell ? cell.return_pct * 100 : null;
  const cellMaxDdPct = cell ? cell.max_drawdown * 100 : null;
  const cellTrades = cell ? cell.trades : null;

  // Paper "Return" shows the marked % of starting capital when known, else the raw $ P&L, else "—".
  const paperReturnStr =
    paperPnlPct !== null
      ? paperPnlPct === 0
        ? "0.0%"
        : `${paperPnlPct > 0 ? "+" : "-"}${Math.abs(paperPnlPct).toFixed(1)}%`
      : paperPnl === null
        ? "—"
        : paperPnl === 0
          ? formatUsd(0, 2)
          : `${paperPnl > 0 ? "+" : "-"}${formatUsd(Math.abs(paperPnl), 2)}`;
  const paperTone = paperPnl === null || paperPnl === 0 ? "" : paperPnl > 0 ? "up" : "dn";

  const btReturnPct = cellReturnPct ?? bestOos;
  const btReturnStr = btReturnPct !== null ? `${btReturnPct >= 0 ? "+" : ""}${btReturnPct.toFixed(1)}%` : "—";
  const btMaxDdStr = cellMaxDdPct !== null ? `−${cellMaxDdPct.toFixed(1)}%` : headlineBt ? `−${(headlineBt.max_dd * 100).toFixed(1)}%` : "—";
  const btTrades = cellTrades !== null ? String(cellTrades) : headlineBt ? String(headlineBt.num_trades) : "—";
  const btWin = headlineBt ? `${(headlineBt.win_rate * 100).toFixed(0)}%` : "—";

  const live = stage === "live";

  // Metric rows: Paper (marked forward) vs Backtest OOS. Sharpe/win-rate have no honest paper value → "—".
  const rows: { metric: string; tip?: string; paper: string; paperTone?: string; bt: string; btTone?: string }[] = [
    {
      metric: "Return",
      tip: "Marked forward P&L (paper) vs the out-of-sample backtest return, after costs.",
      paper: paperReturnStr,
      paperTone,
      bt: btReturnStr,
      btTone: btReturnPct !== null ? (btReturnPct >= 0 ? "up" : "dn") : undefined
    },
    { metric: "Max drawdown", tip: "Worst peak-to-trough drop in equity. — where no forward drawdown is marked yet.", paper: "—", bt: btMaxDdStr },
    { metric: "Sharpe (ann.)", tip: "Annualized Sharpe — no honest paper value at this age, so it reads —.", paper: "—", bt: "—" },
    { metric: "Win rate", tip: "Share of winning periods in the out-of-sample backtest.", paper: "—", bt: btWin },
    { metric: "Trades", tip: "Round-trip trades — too few and the result isn't statistically meaningful.", paper: trades.length ? String(trades.length) : "—", bt: btTrades }
  ];

  return (
    <>
      <div className="tbl-scroll">
        <table className="phase-tbl" style={{ marginBottom: 18 }}>
          <thead>
            <tr>
              <th>Metric</th>
              <th className="col-paper">Paper</th>
              <th>Backtest (OOS)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric}>
                <td data-tip={r.tip}>{r.metric}</td>
                <td className={cn("col-paper", r.paperTone)}>{r.paper}</td>
                <td className={r.btTone ?? ""}>{r.bt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Phase table — Backtest → Paper → Live, with the Live row filling after arming. */}
      <div className="tbl-scroll">
        <table className="phase-tbl">
          <thead>
            <tr>
              <th>Phase</th>
              <th>Since</th>
              <th>Return</th>
              <th>Days</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Backtest</td>
              <td>OOS</td>
              <td className={btReturnPct !== null ? (btReturnPct >= 0 ? "up" : "dn") : ""}>{btReturnStr}</td>
              <td>{formatOosWindow(headlineBt?.oos_window_days) ?? "—"}</td>
            </tr>
            <tr>
              <td>Paper</td>
              <td>{trades.length ? dateTimeParts(sortedFirstTs(trades))?.date ?? "—" : "—"}</td>
              <td className={cn("col-paper", paperTone)}>{paperReturnStr}</td>
              <td>{ageDays !== null ? `${ageDays}d` : "—"}</td>
            </tr>
            <tr className={live ? "" : "phase-live-pending"}>
              <td>Live</td>
              <td>—</td>
              <td>{live ? "—" : <span className="pending-pill">fills after arming</span>}</td>
              <td>—</td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── Gate tab: DSR / OOS / PBO / Max DD / canary / Invested / provenance. Every value off the strongest backtest
// (per-cell Max-DD/Return when a cell is focused). Invested is served on the contract → shown here (not a box). ──
function GatePanel({
  headlineBt,
  holdout,
  invested,
  spec,
  origin,
  cell
}: {
  headlineBt: Backtest | null;
  holdout: { passed: boolean | null; deflatedSharpe: number | null };
  invested: number | null;
  spec: Record<string, unknown>;
  origin?: string | null;
  cell?: LabSymbolRow | null;
}) {
  const dsrProb = headlineBt?.deflated_sharpe_prob ?? null;
  const dsrStr = dsrProb !== null ? dsrProb.toFixed(2) : headlineBt ? (headlineBt.passed_gates ? "≥0.95" : "<0.95") : "—";
  const cellReturnPct = cell ? cell.return_pct * 100 : null;
  const cellMaxDdPct = cell ? cell.max_drawdown * 100 : null;
  const oosStr = cellReturnPct !== null
    ? `${cellReturnPct >= 0 ? "+" : ""}${cellReturnPct.toFixed(1)}%`
    : headlineBt
      ? `${headlineBt.oos_return >= 0 ? "+" : ""}${(headlineBt.oos_return * 100).toFixed(1)}%`
      : "—";
  const oosTone = cellReturnPct !== null ? (cellReturnPct >= 0 ? "up" : "dn") : headlineBt && headlineBt.oos_return >= 0 ? "up" : "";
  const ddStr = cellMaxDdPct !== null ? `~${cellMaxDdPct.toFixed(1)}%` : headlineBt ? `~${(headlineBt.max_dd * 100).toFixed(1)}%` : "—";
  const prov = provenanceOf(origin, referencedFeatures(spec));

  // Canary / safety leg off the real spec exit, when present.
  const exit = isRecord(spec.exit) ? spec.exit : null;
  const canary = exit && typeof exit.canary === "string" ? exit.canary : null;

  return (
    <table className="kv-tbl">
      <tbody>
        <tr>
          <td className="k" data-tip="Deflated-Sharpe PROBABILITY — the 0-to-1 confidence the edge is real after discounting how many variants were tried. The Gate's 0.95 bar checks THIS number.">DSR (deflated Sharpe)</td>
          <td className="v">{dsrStr} {headlineBt ? <span className="hint">≥ 0.95 required</span> : null}</td>
        </tr>
        <tr>
          <td className="k" data-tip="Out-of-sample return on the untouched holdout — data never seen during fitting.">Out-of-sample return</td>
          <td className={cn("v", oosTone)}>{oosStr}</td>
        </tr>
        <tr>
          <td className="k" data-tip="Probability of Backtest Overfitting — the chance the result is curve-fit noise. Lower is better; the Gate wants < 0.50.">CSCV-PBO</td>
          <td className="v">{headlineBt ? headlineBt.pbo.toFixed(2) : "—"} {headlineBt ? <span className="hint">{headlineBt.pbo < PBO_CEILING ? "low overfit probability" : "high overfit — blocked"}</span> : null}</td>
        </tr>
        <tr>
          <td className="k" data-tip="Maximum drawdown — the worst peak-to-trough drop in equity over the test.">Max drawdown</td>
          <td className="v">{ddStr}</td>
        </tr>
        <tr>
          <td className="k" data-tip="The one-shot untouched holdout — did the edge survive data it was never fit to (the most honest 'is it real' check).">Holdout (OOS)</td>
          <td className={cn("v", holdout.passed === null ? "" : holdout.passed ? "up" : "dn")}>{holdout.passed === null ? "—" : holdout.passed ? "Held" : "Failed"}</td>
        </tr>
        {canary ? (
          <tr>
            <td className="k" data-tip="The breadth / regime rule that flips the strategy to its safety leg.">Canary rule</td>
            <td className="v">{canary}</td>
          </tr>
        ) : null}
        <tr>
          <td className="k" data-tip="Capital committed to this track — the paper book's starting size.">Invested</td>
          <td className="v tab">{invested != null ? formatUsd(invested, 2) : "—"}</td>
        </tr>
        <tr>
          <td className="k">Provenance</td>
          <td className="v">
            <span className="prov" data-tip={prov.tip}>{prov.label}</span>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

// ── Spec tab: family / rule / rebalance / venue / universe / safety-leg — all off the real spec, honest "—".
// Building blocks + registry + cost basis + lifecycle trace live here too (the deep technical detail). ──
function SpecPanel({ strategy, spec, holdings }: { strategy: StrategyDetailResponse; spec: Record<string, unknown>; holdings: string[] }) {
  const rationale = typeof spec.rationale === "string" && spec.rationale ? spec.rationale : null;
  const lane = laneOf(spec);
  const kind = strategyKindOf(spec);
  const venue = venueLabel(spec);
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const rebalance =
    horizon && typeof horizon.rebalance === "string"
      ? horizon.rebalance
      : horizon && typeof horizon.bar_size === "string"
        ? horizon.bar_size
        : null;
  const exit = isRecord(spec.exit) ? spec.exit : null;
  const safety = exit && typeof exit.safety_leg === "string"
    ? exit.safety_leg
    : exit && typeof exit.canary === "string"
      ? `Breadth warning → safety leg (${exit.canary})`
      : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <table className="kv-tbl">
        <tbody>
          <tr>
            <td className="k">Family</td>
            <td className="v">{kind.label} · {lane.label} lane</td>
          </tr>
          <tr>
            <td className="k">Rule</td>
            <td className="v">{rationale ?? <span className="quiet">—</span>}</td>
          </tr>
          <tr>
            <td className="k">Rebalance</td>
            <td className="v">{rebalance ?? <span className="quiet">—</span>}</td>
          </tr>
          <tr>
            <td className="k">Venue</td>
            <td className="v">{venue ?? <span className="quiet">—</span>}</td>
          </tr>
          <tr>
            <td className="k">Universe</td>
            <td className="v tab">{holdings.length ? holdings.join(" ") : <span className="quiet">—</span>}</td>
          </tr>
          <tr>
            <td className="k">Safety leg</td>
            <td className="v">{safety ?? <span className="quiet">—</span>}</td>
          </tr>
        </tbody>
      </table>

      <div>
        <div className="psec-title">Building blocks</div>
        <SpecBlocks spec={strategy.spec} />
        {strategy.version_id ? <RegistryBlocks versionId={strategy.version_id} /> : null}
      </div>

      {strategy.version_id ? <CostBasisSelector versionId={strategy.version_id} /> : null}
      {strategy.version_id ? <LifecycleTrace versionId={strategy.version_id} /> : null}
    </div>
  );
}

type TabKey = "trades" | "stats" | "gate" | "spec";

// ── The full sheet body — used by the SidePanel and the standalone page. ──
// `cell` (optional): the clicked (algo × asset × venue) backtest_symbols cell. When present, the BACKTEST-phase
// headline numbers (Return / Max DD / Trades + the equity box) read this cell's STANDALONE truth instead of the
// pooled `backtests` aggregate. The forward money band stays per-track marked money (already honest, not pooled).
export function StrategySheet({ strategy, stageOverride, origin, cell }: { strategy: StrategyDetailResponse; stageOverride?: Stage; origin?: string | null; cell?: LabSymbolRow | null }) {
  const [tab, setTab] = useState<TabKey>("trades");

  // The contract declares trades/backtests as non-null, but the engine can omit them (null) — normalize to
  // empty arrays HERE so every downstream `.length`/spread/`.some` is safe and a partial response can't white-screen.
  const trades = strategy.trades ?? [];
  const backtests = strategy.backtests ?? [];
  const totalFee = feeTotalFromTrades(trades);
  const stage = stageOverride ?? deriveStage(trades, backtests);
  const ageDays = trackAgeDays(trades);
  const headlineBt = headlineBacktest(backtests);
  const bestOos = bestOosPct(backtests);
  const holdout = holdoutVerdict(strategy.holdout);
  const spec = (strategy.spec ?? {}) as Record<string, unknown>;
  const holdings = currentHoldings(spec);

  // Forward P&L = the engine's MARKED total (realized + unrealized = value − starting_capital), off the
  // scope='track' snapshot — NEVER the cash-flow sum of opening buys. null until the track is marked.
  const paperPnl = strategy.pnl_usd ?? null;
  const paperPnlPct =
    strategy.pnl_usd != null && strategy.starting_capital ? (strategy.pnl_usd / strategy.starting_capital) * 100 : null;

  // The strategy's own plain-language rationale off the real spec — the honest "what this does" fallback.
  const specRationale = typeof spec.rationale === "string" ? spec.rationale : null;

  return (
    <div className="sheet-stack">
      {/* ── Card 1 — merged: title + Go-live/Stop + status + Gated badge + meta + number boxes ── */}
      <TopCard
        strategy={strategy}
        stage={stage}
        ageDays={ageDays}
        headlineBt={headlineBt}
        cell={cell}
        paperPnl={paperPnl}
        paperPnlPct={paperPnlPct}
        totalFee={totalFee}
        holdings={holdings}
      />

      {/* ── Card 2 — equity chart (short) + "What this does" ── */}
      <div className="sheet-card">
        <EquityPanel versionId={strategy.version_id ?? null} forwardCurve={strategy.forward_equity ?? []} stage={stage} cell={cell ?? null} />
        <div style={{ marginTop: 14 }}>
          <AiSummary
            summaryMd={strategy.summary_md}
            stale={strategy.summary_stale}
            updatedAt={strategy.summary_updated_at}
            specRationale={specRationale}
            stage={stage}
            gate={
              headlineBt
                ? {
                    passedGates: headlineBt.passed_gates,
                    deflatedSharpe: headlineBt.deflated_sharpe,
                    deflatedSharpeProb: headlineBt.deflated_sharpe_prob ?? null,
                    pbo: headlineBt.pbo,
                    oosReturn: cell ? cell.return_pct : headlineBt.oos_return,
                    oosWindowDays: headlineBt.oos_window_days,
                    maxDd: cell ? cell.max_drawdown : headlineBt.max_dd
                  }
                : null
            }
          />
        </div>
      </div>

      {/* ── Card 3 — Technical details with the tab bar (Trades default · Stats · Gate · Spec) ── */}
      <div className="sheet-card">
        <div className="sheet-tech-title">Technical details</div>
        <div className="sheet-tabbar" role="tablist">
          {(["trades", "stats", "gate", "spec"] as TabKey[]).map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              className={cn("sheet-tab", tab === k && "on")}
              onClick={() => setTab(k)}
            >
              {k === "trades" ? "Trades" : k === "stats" ? "Stats" : k === "gate" ? "Gate" : "Spec"}
            </button>
          ))}
        </div>

        {tab === "trades" ? <TradesPanel trades={trades} stage={stage} /> : null}
        {tab === "stats" ? (
          <StatsPanel
            headlineBt={headlineBt}
            paperPnl={paperPnl}
            paperPnlPct={paperPnlPct}
            trades={trades}
            ageDays={ageDays}
            bestOos={bestOos}
            cell={cell}
            stage={stage}
          />
        ) : null}
        {tab === "gate" ? (
          <GatePanel headlineBt={headlineBt} holdout={holdout} invested={strategy.invested_usd ?? null} spec={spec} origin={origin} cell={cell} />
        ) : null}
        {tab === "spec" ? <SpecPanel strategy={strategy} spec={spec} holdings={holdings} /> : null}
      </div>
    </div>
  );
}
