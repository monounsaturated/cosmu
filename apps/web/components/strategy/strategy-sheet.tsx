// module: StrategySheet — the SHARED per-Version detail body, rendered identically inside the screener's
// right `SidePanel` and on the standalone `/strategy/[id]` bento page. It reproduces the v18 reference
// sheet (cosmu-final-v18.html `fundingCarryPanel`/`templatePanel`) as the SECTION STRUCTURE only — every
// number is bound to a REAL field off StrategyDetailResponse, never the mockup's synthetic arrays.
//
// HONESTY: the detail contract carries only spec/params/code/notes/holdout/backtests/trades. So:
//   • money-band → only P&L + Fees are real (off the fills); Value/Invested render "—".
//   • equity     → the realized cash-flow curve from real trades only; honest empty when < 2 fills.
//   • AI summary → summary_md only; honest "no summary yet" when null.
//   • gate chips + phase-comparison → the strongest backtest's measured DSR/PBO/Max-DD/OOS/trades; every
//     cell with no real source (Paper/Live columns, Sharpe-in-paper, …) is an explicit "—".
//   • building blocks → derived from the real spec (SpecBlocks); "—" where a block is absent.
//   • trades → the real Execution blotter; activity → derived from real fills only.

import type { Backtest, Execution, Point, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { MoneyBand, type MoneyBandData } from "./money-band";
import { AiSummary } from "./ai-summary";
import { CostBasisSelector } from "./cost-basis-selector";
import { PhasedEquity } from "./phased-equity";
import { SpecBlocks } from "./spec-view";
import { StageControl, type Stage } from "./stage-control";
import { cn, formatUsd } from "@/lib/utils";

// ── Honest derivations off the real detail response (same logic the prior detail page used) ──

// Realized cash-flow curve: cumulative (sells add, buys subtract, fees always subtract), seeded at 0.
export function simCurveFromTrades(trades: Execution[]): Point[] {
  if (trades.length < 2) return [];
  let acc = 0;
  return trades.map((t) => {
    const gross = t.side === "sell" ? t.qty * t.price : -t.qty * t.price;
    acc += gross - t.fee;
    return { ts: t.ts, value: acc };
  });
}

export function ledgerFromTrades(trades: Execution[]): { totalFee: number | null; realizedPnl: number | null } {
  if (trades.length === 0) return { totalFee: null, realizedPnl: null };
  let totalFee = 0;
  let pnl = 0;
  for (const t of trades) {
    totalFee += t.fee;
    pnl += (t.side === "sell" ? t.qty * t.price : -t.qty * t.price) - t.fee;
  }
  return { totalFee, realizedPnl: pnl };
}

// Stage derived honestly from the contract shape: fills → paper; backtests only → backtest; none → queued.
// We never claim "live"/"killed" — neither is recoverable here, so we never invent them.
export function deriveStage(trades: Execution[], backtests: Backtest[]): Stage {
  if (trades.length > 0) return "paper";
  if (backtests.length > 0) return "backtest";
  return "queued";
}

export function trackAgeDays(trades: Execution[]): number | null {
  if (trades.length < 2) return null;
  const ts = trades.map((t) => Date.parse(t.ts)).filter((n) => !Number.isNaN(n));
  if (ts.length < 2) return null;
  const days = Math.round((Math.max(...ts) - Math.min(...ts)) / 86_400_000);
  return days > 0 ? days : null;
}

// The representative backtest for the headline chips: prefer a passed one, else strongest by DSR.
export function headlineBacktest(backtests: Backtest[]): Backtest | null {
  return (
    backtests.find((bt) => bt.passed_gates) ??
    [...backtests].sort((a, b) => b.deflated_sharpe - a.deflated_sharpe)[0] ??
    null
  );
}

export function bestOosPct(backtests: Backtest[]): number | null {
  const passed = backtests.filter((b) => b.passed_gates);
  const pool = passed.length ? passed : backtests;
  if (!pool.length) return null;
  const v = Math.max(...pool.map((b) => b.oos_return)) * 100;
  return Number.isFinite(v) ? v : null;
}

// The OOS window as a human span ("~2.4yr" / "~8mo" / "~120d") — the actual length behind the OOS %, so the
// Duration row reads "~2.4yr" instead of the bare literal "OOS". null when the engine has no window length.
function formatOosWindow(days: number | null | undefined): string | null {
  if (!days || days <= 0) return null;
  if (days >= 360) return `~${(days / 365).toFixed(1)}yr`;
  if (days >= 60) return `~${Math.round(days / 30)}mo`;
  return `~${Math.round(days)}d`;
}

// Gate reference (mirrors gate-chips): PBO must be under 0.50 to pass.
const PBO_CEILING = 0.5;

// ── Phase comparison: Backtest OOS / Paper / Live side by side. Live is not on this contract → all "—".
// This table is now the SINGLE home for the gate metrics too (DSR / PBO / Max DD / OOS) — the separate
// "Gate metrics" chip row was removed, so every measured number lives in one place with its phase columns. ──
function PhaseComparison({
  headlineBt,
  paperPnl,
  trades,
  ageDays,
  bestOos
}: {
  headlineBt: Backtest | null;
  paperPnl: number | null;
  trades: Execution[];
  ageDays: number | null;
  bestOos: number | null;
}) {
  // `tip` defines each metric ONCE, in plain words (hover) — so a non-expert can read the table without a
  // glossary elsewhere. These replace the removed gate-metric chips' tooltips.
  const rows: { metric: string; tip?: string; bt: string; btTone?: string; paper: string; paperTone?: string; live: string }[] = [
    {
      metric: "Return",
      tip: "Total profit over the out-of-sample test window, after costs. Green = profitable.",
      bt: bestOos !== null ? `${bestOos >= 0 ? "+" : ""}${bestOos.toFixed(1)}%` : "—",
      btTone: bestOos !== null ? (bestOos >= 0 ? "up" : "dn") : undefined,
      paper: paperPnl !== null ? `${paperPnl >= 0 ? "+" : "-"}${formatUsd(Math.abs(paperPnl), 0)}` : "—",
      paperTone: paperPnl !== null ? (paperPnl >= 0 ? "up" : "dn") : undefined,
      live: "—"
    },
    {
      metric: "Sharpe (DSR)",
      tip: "Deflated Sharpe Ratio — risk-adjusted return, discounted for how many variants were tried (so luck can't fake an edge). The Gate wants ≥ 0.95.",
      bt: headlineBt ? headlineBt.deflated_sharpe.toFixed(2) : "—",
      btTone: headlineBt ? (headlineBt.deflated_sharpe >= 0.95 ? "up" : undefined) : undefined,
      paper: "—",
      live: "—"
    },
    {
      metric: "PBO",
      tip: "Probability of Backtest Overfitting — the chance the result is curve-fit noise, not a real edge. Lower is better; the Gate wants < 0.50.",
      bt: headlineBt ? headlineBt.pbo.toFixed(2) : "—",
      btTone: headlineBt ? (headlineBt.pbo < PBO_CEILING ? "up" : "dn") : undefined,
      paper: "—",
      live: "—"
    },
    {
      metric: "Max DD",
      tip: "Maximum Drawdown — the worst peak-to-trough drop in equity over the test. Smaller = less painful to hold.",
      bt: headlineBt ? `${(headlineBt.max_dd * 100).toFixed(1)}%` : "—",
      paper: "—",
      live: "—"
    },
    {
      metric: "Trades",
      tip: "How many round-trip trades the test took — too few and the result isn't statistically meaningful.",
      bt: headlineBt ? String(headlineBt.num_trades) : "—",
      paper: trades.length ? String(trades.length) : "—",
      live: "—"
    },
    {
      metric: "Duration",
      tip: "Length of the out-of-sample (OOS) window — the unseen period the strategy was tested on, AFTER the data it was built on. Longer = more trustworthy.",
      bt: formatOosWindow(headlineBt?.oos_window_days) ?? (headlineBt ? "OOS" : "—"),
      paper: ageDays !== null ? `${ageDays}d` : "—",
      live: "—"
    }
  ];
  return (
    <div className="psec">
      <div className="psec-title">Phase comparison</div>
      <div className="tbl-scroll">
        <table className="phase-tbl">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Backtest OOS</th>
              <th className="col-paper">Paper</th>
              <th className="col-live">Live</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric}>
                <td data-tip={r.tip}>{r.metric}</td>
                <td className={r.btTone ?? ""}>{r.bt}</td>
                <td className={cn("col-paper", r.paperTone)}>{r.paper}</td>
                <td className="col-live">{r.live}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// "Jun 09 14:22" parts, split so the time reads quiet.
function dateTimeParts(ts: string): { date: string; time: string } | null {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return {
    date: d.toLocaleDateString("en-US", { month: "short", day: "2-digit" }),
    time: d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
  };
}

function fillPnl(t: Execution): number {
  return (t.side === "sell" ? t.qty * t.price : -t.qty * t.price) - t.fee;
}

// ── Recent trades — the real Execution blotter (newest first), in the bento `.mini-tbl`. ──
function RecentTrades({ trades }: { trades: Execution[] }) {
  if (trades.length === 0) {
    return (
      <div className="psec" id="sheet-trades">
        <div className="psec-title">Recent trades</div>
        <p className="quiet" style={{ fontSize: 11 }}>No fills yet — trades appear here as this track trades on live data. Nothing is fabricated.</p>
      </div>
    );
  }
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  return (
    <div className="psec" id="sheet-trades">
      <div className="psec-title">Recent trades · {trades.length}</div>
      <div className="tbl-scroll">
        <table className="mini-tbl">
          <thead>
            <tr>
              <th>Date · time</th>
              <th>Side</th>
              <th className="r">Price</th>
              <th className="r">Qty</th>
              <th className="r">Fee</th>
              <th className="r">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((t) => {
              const dt = dateTimeParts(t.ts);
              const pnl = fillPnl(t);
              return (
                <tr key={t.id}>
                  <td>
                    {dt ? (
                      <>
                        {dt.date} <span className="quiet">{dt.time}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{t.side === "buy" ? "Buy" : "Sell"}</td>
                  <td className="r tab">{formatUsd(t.price, 2)}</td>
                  <td className="r tab">{t.qty}</td>
                  <td className="r tab muted">{formatUsd(t.fee, 2)}</td>
                  <td className={cn("r tab", pnl >= 0 ? "up" : "dn")}>
                    {pnl >= 0 ? "+" : "-"}
                    {formatUsd(Math.abs(pnl), 2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Activity — derived from real fills only (entered/closed events), newest first. Honest empty otherwise. ──
function Activity({ trades }: { trades: Execution[] }) {
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)).slice(0, 8);
  return (
    <div className="psec" id="sheet-activity">
      <div className="psec-title">Activity</div>
      <div className="act-list">
        {ordered.length === 0 ? (
          <div className="act-row">
            <span className="act-time">—</span>
            <span className="act-text quiet">No activity yet — events appear here as this track fills.</span>
          </div>
        ) : (
          ordered.map((t, i) => {
            const dt = dateTimeParts(t.ts);
            const pnl = fillPnl(t);
            return (
              <div key={t.id} className={i === 0 ? "act-row cur-ev" : "act-row"}>
                <span className="act-time">{dt ? `${dt.date}, ${dt.time}` : "—"}</span>
                <span className="act-text">
                  <strong>{t.side === "buy" ? "Bought" : "Sold"}</strong> {t.qty} @ {formatUsd(t.price, 2)}
                  {t.venue ? <span className="quiet"> · {t.venue}</span> : null} ·{" "}
                  <span className={pnl >= 0 ? "up" : "dn"}>
                    {pnl >= 0 ? "+" : "-"}
                    {formatUsd(Math.abs(pnl), 2)}
                  </span>
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── The full sheet body — used by the SidePanel and the standalone page. ──
export function StrategySheet({ strategy, stageOverride }: { strategy: StrategyDetailResponse; stageOverride?: Stage }) {
  const trades = strategy.trades;
  const simCurve = simCurveFromTrades(trades);
  const ledger = ledgerFromTrades(trades);
  // Prefer the engine's canonical stage (passed from the screener row) so the sheet badge never disagrees
  // with the table; fall back to the contract-shape heuristic for the standalone /strategy/[id] page.
  const stage = stageOverride ?? deriveStage(trades, strategy.backtests);
  const ageDays = trackAgeDays(trades);
  const headlineBt = headlineBacktest(strategy.backtests);
  const bestOos = bestOosPct(strategy.backtests);
  const paperPnl = simCurve.length >= 2 ? simCurve[simCurve.length - 1].value : null;
  // The strategy's own plain-language rationale off the real spec — the honest "what this does" fallback when
  // no operator summary is written yet (documented strategies carry a rich rationale describing the mechanism).
  const specRationale =
    strategy.spec && typeof (strategy.spec as Record<string, unknown>).rationale === "string"
      ? ((strategy.spec as Record<string, string>).rationale)
      : null;

  const money: MoneyBandData = {
    valueUsd: null,
    investedUsd: null,
    pnlUsd: ledger.realizedPnl,
    pnlPct: null,
    feesUsd: ledger.totalFee,
    pnlSub: ageDays !== null ? `${ageDays}d · realized` : "realized",
    feesSub: "off real fills"
  };

  return (
    <>
      <StageControl
        stage={stage}
        ageDays={ageDays}
        strategyName={strategy.name}
        versionId={strategy.version_id}
        goLiveEligible={stage === "paper" || Boolean(headlineBt?.passed_gates)}
      />

      <MoneyBand data={money} />

      <PhasedEquity paperCurve={simCurve} />

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
                pbo: headlineBt.pbo,
                oosReturn: headlineBt.oos_return,
                oosWindowDays: headlineBt.oos_window_days,
                maxDd: headlineBt.max_dd
              }
            : null
        }
      />

      <PhaseComparison headlineBt={headlineBt} paperPnl={paperPnl} trades={trades} ageDays={ageDays} bestOos={bestOos} />

      <CostBasisSelector versionId={strategy.version_id} />

      <div className="psec">
        <div className="psec-title">Building blocks</div>
        <SpecBlocks spec={strategy.spec} />
      </div>

      <RecentTrades trades={trades} />

      <Activity trades={trades} />
    </>
  );
}
