import { ScrollText } from "lucide-react";
import { engineConfigured, getStrategy } from "../../data";
import type { Backtest, Execution, Point } from "@cosmu/contracts-ts";
import { LaunchLiveButton } from "@/components/live/launch-live-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { SpecView } from "@/components/strategy/spec-view";
import { AiSummary } from "@/components/strategy/ai-summary";
import { MoneyBand, type MoneyBandData } from "@/components/strategy/money-band";
import { GateChips } from "@/components/strategy/gate-chips";
import { PhasedEquity } from "@/components/strategy/phased-equity";
import { StageControl, type Stage } from "@/components/strategy/stage-control";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { StrategyHeader } from "@/components/strategies/strategy-header";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { Tabs, type TabItem, GaugeBar } from "@/components/ui/viz";
import { cn, formatUsd } from "@/lib/utils";

// The REAL deterministic Gate thresholds (apps/engine/cosmu/config/settings.py). Surfaced here so the
// verdict reads against the SAME numbers the engine gates on — never hand-picked display thresholds.
const GATE = { minTrades: 30, maxDrawdownPct: 0.25, maxPbo: 0.5, minDeflatedSharpe: 0 } as const;

// Derive a sim equity curve from the strategy's trade log: cumulative realized cash flow (sells add,
// buys subtract, fees always subtract), seeded at 0. Honest — built only from the real trades the engine
// returned; no fabricated track record.
function simCurveFromTrades(trades: Execution[]): Point[] {
  if (trades.length < 2) return [];
  let acc = 0;
  return trades.map((t) => {
    const gross = t.side === "sell" ? t.qty * t.price : -t.qty * t.price;
    acc += gross - t.fee;
    return { ts: t.ts, value: acc };
  });
}

// Costs + realized P&L off the REAL fills only — never fabricated. Total fees, per-trade average, and
// fees as a share of gross traded notional. Realized P&L is the final point of the cumulative cash-flow
// curve. Returns nulls when there are no fills so the page shows honest "—" / empty states.
function ledgerFromTrades(trades: Execution[]): {
  totalFee: number | null;
  perTradeFee: number | null;
  pctOfNotional: number | null;
  realizedPnl: number | null;
} {
  if (trades.length === 0) return { totalFee: null, perTradeFee: null, pctOfNotional: null, realizedPnl: null };
  let totalFee = 0;
  let notional = 0;
  let pnl = 0;
  for (const t of trades) {
    totalFee += t.fee;
    notional += Math.abs(t.qty * t.price);
    pnl += (t.side === "sell" ? t.qty * t.price : -t.qty * t.price) - t.fee;
  }
  return {
    totalFee,
    perTradeFee: totalFee / trades.length,
    pctOfNotional: notional > 0 ? (totalFee / notional) * 100 : null,
    realizedPnl: pnl
  };
}

// Derive the lifecycle stage HONESTLY from the detail response shape — the contract carries no stage
// field, so this is the only non-fabricating read available:
//   • fills present            → a forward track on live data exists → "paper" (no money; the engine's
//                                 "Paper" framing).
//   • backtests but no fills   → "backtest".
//   • no backtests at all      → "queued".
// We never claim "live" or "killed" — neither is recoverable from this contract, so we don't invent them.
function deriveStage(trades: Execution[], backtests: Backtest[]): Stage {
  if (trades.length > 0) return "paper";
  if (backtests.length > 0) return "backtest";
  return "queued";
}

// Span of the trade track in whole days, for the stage badge age + money-band sub-lines. null when < 2 fills.
function trackAgeDays(trades: Execution[]): number | null {
  if (trades.length < 2) return null;
  const ts = trades.map((t) => Date.parse(t.ts)).filter((n) => !Number.isNaN(n));
  if (ts.length < 2) return null;
  const days = Math.round((Math.max(...ts) - Math.min(...ts)) / 86_400_000);
  return days > 0 ? days : null;
}

// Render a free-form holdout record (e.g. {passed, deflated_sharpe, seen_once}) as labelled rows. The
// contract types holdout as Record<string, unknown>; format known number/bool shapes nicely.
function holdoutRows(holdout: Record<string, unknown>): { label: string; value: string; tone?: "up" | "down" }[] {
  return Object.entries(holdout).map(([k, v]) => {
    const label = k.replace(/_/g, " ");
    if (typeof v === "boolean") return { label, value: v ? "yes" : "no", tone: v ? "up" : "down" };
    if (typeof v === "number") return { label, value: v.toFixed(2) };
    return { label, value: String(v) };
  });
}

// Pull the glanceable lane/thesis off the REAL detail fields. Defensive — the spec is typed
// Record<string, unknown>, so unknown shapes yield null and the header simply omits that chip.
function strategySummary(
  spec: Record<string, unknown>,
  backtests: Backtest[]
): { thesis: string | null; venue: string | null; timeframe: string | null; bestOos: number | null } {
  const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
  const universe = isRecord(spec.universe) ? spec.universe : null;
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const venues = universe && Array.isArray(universe.venues) ? (universe.venues as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const tfRaw = horizon && (typeof horizon.timeframe === "string" ? horizon.timeframe : null);
  const passedBts = backtests.filter((b) => b.passed_gates);
  const pool = passedBts.length ? passedBts : backtests;
  const bestOos = pool.length ? Math.max(...pool.map((b) => b.oos_return)) * 100 : null;
  return {
    thesis: typeof spec.rationale === "string" && spec.rationale ? spec.rationale : null,
    venue: venues.length ? venues.join(" · ") : null,
    timeframe: tfRaw,
    bestOos: bestOos !== null && Number.isFinite(bestOos) ? bestOos : null
  };
}

// Strategy detail is the DEFINITIVE inspect view for one Version, redrawn in v18 as a focused sheet:
// stage badge + Stop/Start, a money band, the phased equity panel (backtest folds → paper curve → live),
// the AI summary, gate chips, a phase-comparison table, the trade blotter (date · time + $ P&L), then the
// spec/code/notes a tap away. All from the existing strategy detail endpoint — nothing fabricated; honest
// empty states throughout.
export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { strategy, connected } = await getStrategy(id);

  if (!connected || !strategy.version_id) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
        <StrategyStages />
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">version</div>
          <h1 className="mt-1 font-mono text-2xl font-semibold tracking-tight text-foreground">{id}</h1>
        </div>
        <NotConnected
          configured={engineConfigured}
          what="This Version's full picture — spec, compiled code, trade blotter, OOS/holdout evidence, and the agent post-mortem — comes from the live engine. Nothing is fabricated."
        />
      </div>
    );
  }

  const trades = strategy.trades;
  const simCurve = simCurveFromTrades(trades);
  const ledger = ledgerFromTrades(trades);
  const holdout = holdoutRows(strategy.holdout as Record<string, unknown>);
  const passed = strategy.backtests.some((bt: Backtest) => bt.passed_gates);
  const summary = strategySummary(strategy.spec, strategy.backtests);
  const stage = deriveStage(trades, strategy.backtests);
  const ageDays = trackAgeDays(trades);

  // The representative backtest for the headline chips: prefer a passed one, else the strongest by
  // deflated Sharpe (so the strip reflects the best honest evidence this Version has produced).
  const headlineBt =
    strategy.backtests.find((bt) => bt.passed_gates) ??
    [...strategy.backtests].sort((a, b) => b.deflated_sharpe - a.deflated_sharpe)[0] ??
    null;

  // Money band — only P&L and Fees are real on this contract; Value/Invested are not carried, so they
  // render an explicit "—" rather than a fabricated 0 (HONESTY rule).
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
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <StrategyStages />

      {/* ── Sheet top: stage badge + matching Stop/Start affordance. Launch-live is offered only when the
          Gate has passed (the same condition the old header used). ── */}
      <StageControl
        stage={stage}
        ageDays={ageDays}
        strategyName={strategy.name}
        gatePassed={passed}
        extraAction={passed ? <LaunchLiveButton versionId={strategy.version_id} strategyName={strategy.name} /> : undefined}
      />

      {/* ── ONE title block — verdict, name, lane, thesis, honest headline OOS. ── */}
      <StrategyHeader
        name={strategy.name}
        versionId={strategy.version_id}
        passed={passed}
        lane={[summary.venue, summary.timeframe]}
        thesis={summary.thesis}
        bestOos={summary.bestOos}
      />

      {/* ── Money band — Value · Invested · P&L · Fees. Honest "—" where the contract carries no value. ── */}
      <MoneyBand data={money} />

      {/* ── Phased equity — backtest folds → paper curve → live (greyed where not reached). ── */}
      <Card>
        <CardContent className="pt-5">
          <PhasedEquity backtests={strategy.backtests} paperCurve={simCurve} height={240} />
        </CardContent>
      </Card>

      {/* ── AI summary — plain-language, from recorded facts only; badge names the source. ── */}
      <AiSummary summaryMd={strategy.summary_md} stale={strategy.summary_stale} updatedAt={strategy.summary_updated_at} />

      {/* ── Gate chips — the verdict as four pass/warn chips against the REAL Gate thresholds. ── */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-quiet">
          Gate metrics
          <Tooltip content="The deterministic Gate's pass/fail read, evaluated on the strongest backtest: deflated Sharpe > 0, PBO < 0.50, max drawdown < 25%. Green cleared, amber blocked, — when not yet measured." />
        </div>
        <GateChips backtest={headlineBt} />
      </div>

      {/* ── Phase comparison — backtest OOS vs paper vs live, side by side. Live unavailable on this
          contract, so its column is an honest "—". ── */}
      <PhaseComparison headlineBt={headlineBt} simCurve={simCurve} trades={trades} ageDays={ageDays} bestOos={summary.bestOos} />

      {/* ── Progressive disclosure — Gate detail, full trade blotter, spec/code, notes a tap away. ── */}
      <Tabs
        ariaLabel="Strategy detail sections"
        tabs={[
          { id: "gate", label: "Gate", count: strategy.backtests.length, content: <GateTab backtests={strategy.backtests} holdout={holdout} /> },
          { id: "trades", label: "Trades", count: trades.length, content: <TradesTab trades={trades} ledger={ledger} /> },
          { id: "spec", label: "Spec", content: <SpecTab spec={strategy.spec} params={strategy.params} code={strategy.generated_code} /> },
          { id: "notes", label: "Notes", content: <NotesTab notes={strategy.notes_md} /> }
        ] satisfies TabItem[]}
      />
    </div>
  );
}

// ── Phase comparison: the headline metrics across Backtest OOS / Paper / Live, side by side. Every value
// is a REAL measured number or an honest "—". Live is not on this contract, so that column is all "—". ──
function PhaseComparison({
  headlineBt,
  simCurve,
  trades,
  ageDays,
  bestOos
}: {
  headlineBt: Backtest | null;
  simCurve: Point[];
  trades: Execution[];
  ageDays: number | null;
  bestOos: number | null;
}) {
  const paperPnl = simCurve.length >= 2 ? simCurve[simCurve.length - 1].value : null;
  const rows: {
    metric: string;
    bt: string;
    paper: string;
    live: string;
    btTone?: "up" | "down";
    paperTone?: "up" | "down";
  }[] = [
    {
      metric: "Return",
      bt: bestOos !== null ? `${bestOos >= 0 ? "+" : ""}${bestOos.toFixed(1)}%` : "—",
      btTone: bestOos !== null ? (bestOos >= 0 ? "up" : "down") : undefined,
      paper: paperPnl !== null ? `${paperPnl >= 0 ? "+" : "-"}${formatUsd(Math.abs(paperPnl), 0)}` : "—",
      paperTone: paperPnl !== null ? (paperPnl >= 0 ? "up" : "down") : undefined,
      live: "—"
    },
    { metric: "Sharpe (DSR)", bt: headlineBt ? headlineBt.deflated_sharpe.toFixed(2) : "—", paper: "—", live: "—" },
    { metric: "Max DD", bt: headlineBt ? `${(headlineBt.max_dd * 100).toFixed(1)}%` : "—", paper: "—", live: "—" },
    { metric: "Trades", bt: headlineBt ? String(headlineBt.num_trades) : "—", paper: trades.length ? String(trades.length) : "—", live: "—" },
    { metric: "Duration", bt: headlineBt ? "OOS" : "—", paper: ageDays !== null ? `${ageDays}d` : "—", live: "—" }
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          Phase comparison
          <Tooltip content="The headline numbers across the lifecycle: historical out-of-sample (Backtest), forward proof on live data (Paper), and real-capital record (Live). Every cell is a real measured value or an honest — when not available." />
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <THead>
            <TR>
              <TH className="pl-5 whitespace-nowrap">Metric</TH>
              <TH className="text-right whitespace-nowrap">Backtest OOS</TH>
              <TH className="text-right whitespace-nowrap text-iris-soft">Paper</TH>
              <TH className="pr-5 text-right whitespace-nowrap text-up">Live</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((r) => (
              <TR key={r.metric}>
                <TD className="pl-5 font-medium whitespace-nowrap text-foreground">{r.metric}</TD>
                <TD className={cn("text-right tabular whitespace-nowrap", r.btTone === "up" ? "text-up" : r.btTone === "down" ? "text-down" : "text-muted")}>{r.bt}</TD>
                <TD className={cn("text-right tabular whitespace-nowrap", r.paperTone === "up" ? "text-up" : r.paperTone === "down" ? "text-down" : "text-iris-soft/85")}>{r.paper}</TD>
                <TD className="pr-5 text-right tabular whitespace-nowrap text-quiet">{r.live}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ── Gate tab: every backtest's deterministic verdict, plus the untouched holdout. Max-DD-vs-25% gauge
// per card. Mounts only when opened. ──
function GateTab({
  backtests,
  holdout
}: {
  backtests: Backtest[];
  holdout: { label: string; value: string; tone?: "up" | "down" }[];
}) {
  if (backtests.length === 0) {
    return (
      <Card>
        <CardContent className="pt-5">
          <EmptyState title="No backtests yet." hint="Gate verdicts appear here once this Version has been backtested." />
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        {backtests.map((bt) => {
          const ddFrac = Math.min(1, bt.max_dd / GATE.maxDrawdownPct);
          const ddOk = bt.max_dd < GATE.maxDrawdownPct;
          return (
            <Card key={bt.id}>
              <CardHeader>
                <CardTitle className="uppercase tracking-wide">{bt.kind}</CardTitle>
                <Badge variant={bt.passed_gates ? "up" : "down"}>{bt.passed_gates ? "passed" : "blocked"}</Badge>
              </CardHeader>
              <CardContent className="space-y-3.5">
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12.5px]">
                  <Metric label="deflated Sharpe" value={bt.deflated_sharpe.toFixed(2)} ok={bt.deflated_sharpe > GATE.minDeflatedSharpe} />
                  <Metric label="PBO" value={bt.pbo.toFixed(2)} ok={bt.pbo < GATE.maxPbo} />
                  <Metric label="OOS return" value={`${(bt.oos_return * 100).toFixed(1)}%`} tone={bt.oos_return >= 0 ? "up" : "down"} />
                  <Metric label="win rate" value={`${(bt.win_rate * 100).toFixed(0)}%`} />
                  <Metric label="trades" value={String(bt.num_trades)} ok={bt.num_trades >= GATE.minTrades} />
                  <Metric label="max DD" value={`${(bt.max_dd * 100).toFixed(1)}%`} tone="down" />
                </div>
                <div className="space-y-1 border-t border-border/50 pt-3">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-quiet">Drawdown vs 25% limit</span>
                    <span className={cn("tabular font-medium", ddOk ? "text-foreground" : "text-down")}>
                      {(ddFrac * 100).toFixed(0)}% of limit
                    </span>
                  </div>
                  <GaugeBar value={bt.max_dd} max={GATE.maxDrawdownPct} marker={1} tone={ddOk ? "warn" : "down"} />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Untouched holdout — the one-shot, seen-once test that gates promotion. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Untouched holdout
            <Tooltip content="The one-shot, seen-once test. A Version may only meet its holdout once — passing it is what allows promotion." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {holdout.length ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-3">
              {holdout.map((row) => (
                <div key={row.label} className="flex items-center justify-between gap-3">
                  <dt className="text-muted">{row.label}</dt>
                  <dd className={cn("tabular", row.tone === "up" ? "text-up" : row.tone === "down" ? "text-down" : "text-foreground")}>
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-[12px] text-quiet">No holdout recorded — this Version has not met its untouched holdout yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value, ok, tone }: { label: string; value: string; ok?: boolean; tone?: "up" | "down" }) {
  const color = ok === false ? "text-down" : tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground";
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={cn("tabular", color)}>{value}</span>
    </div>
  );
}

// Per-fill P&L for the blotter: the signed cash flow of THIS fill (sells add, buys subtract, fee always
// subtracts). Honest — exactly the cash the engine recorded for the fill, never a fabricated trade-level
// round-trip return (pairing buys to sells is not recoverable from this contract).
function fillPnl(t: Execution): number {
  return (t.side === "sell" ? t.qty * t.price : -t.qty * t.price) - t.fee;
}

// "Jun 12 · 14:22" — date and time of day, split so the time reads quiet. en-US, the mockup's format.
function dateTimeParts(ts: string): { date: string; time: string } | null {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return {
    date: d.toLocaleDateString("en-US", { month: "short", day: "2-digit" }),
    time: d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
  };
}

// ── Trades tab: the full fill log with date · time and a $ P&L per fill. Scrolls horizontally on overflow
// (Table wraps in overflow-x-auto). Mounts only when opened. ──
function TradesTab({
  trades,
  ledger
}: {
  trades: Execution[];
  ledger: { totalFee: number | null; perTradeFee: number | null; pctOfNotional: number | null };
}) {
  if (trades.length === 0) {
    return (
      <Card>
        <CardContent className="pt-5">
          <EmptyState title="No trades yet." hint="Fills appear here as this track trades on live data. Nothing is fabricated." />
        </CardContent>
      </Card>
    );
  }
  // Newest first — the blotter reads most-recent-at-top, like the sheet.
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  return (
    <div className="space-y-3">
      <Card>
        <CardContent className="p-0">
          <Table>
            <THead>
              <TR>
                <TH className="pl-4 whitespace-nowrap">Date · time</TH>
                <TH className="whitespace-nowrap">Side</TH>
                <TH className="text-right whitespace-nowrap">Qty</TH>
                <TH className="text-right whitespace-nowrap">Price</TH>
                <TH className="text-right whitespace-nowrap">Fee</TH>
                <TH className="whitespace-nowrap">Venue</TH>
                <TH className="pr-4 text-right whitespace-nowrap">P&amp;L</TH>
              </TR>
            </THead>
            <TBody>
              {ordered.map((trade) => {
                const dt = dateTimeParts(trade.ts);
                const pnl = fillPnl(trade);
                return (
                  <TR key={trade.id}>
                    <TD className="pl-4 whitespace-nowrap text-foreground">
                      {dt ? (
                        <time dateTime={trade.ts}>
                          {dt.date} <span className="text-quiet">· {dt.time}</span>
                        </time>
                      ) : (
                        "—"
                      )}
                    </TD>
                    <TD className="whitespace-nowrap">
                      <Badge variant={trade.side === "buy" ? "up" : "down"}>{trade.side}</Badge>
                    </TD>
                    <TD className="text-right tabular whitespace-nowrap text-foreground">{trade.qty}</TD>
                    <TD className="text-right tabular whitespace-nowrap text-foreground">{formatUsd(trade.price, 2)}</TD>
                    <TD className="text-right tabular whitespace-nowrap text-muted">{formatUsd(trade.fee, 2)}</TD>
                    <TD className="whitespace-nowrap text-quiet">{trade.venue ?? "—"}</TD>
                    <TD className={cn("pr-4 text-right tabular whitespace-nowrap", pnl >= 0 ? "text-up" : "text-down")}>
                      {pnl >= 0 ? "+" : "-"}
                      {formatUsd(Math.abs(pnl), 2)}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      {/* Costs — the real fee drag on this track, counted off the fills. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Costs
            <Tooltip content="The fees this track has actually paid, counted off its real fills (Execution.fee). The P&L above is already after these costs — this makes the drag explicit, never fabricated." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[12.5px] sm:grid-cols-3">
            <CostStat label="Total fees paid" value={ledger.totalFee !== null ? formatUsd(ledger.totalFee, 2) : "—"} />
            <CostStat label="Avg fee / trade" value={ledger.perTradeFee !== null ? formatUsd(ledger.perTradeFee, 2) : "—"} />
            <CostStat label="Fees vs notional" value={ledger.pctOfNotional !== null ? `${ledger.pctOfNotional.toFixed(3)}%` : "—"} />
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function CostStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">{label}</dt>
      <dd className="text-lg font-semibold tabular tracking-tight text-foreground">{value}</dd>
    </div>
  );
}

// ── Spec tab: the typed hypothesis + the compiled artifact it produced. ──
function SpecTab({
  spec,
  params,
  code
}: {
  spec: Record<string, unknown>;
  params: Record<string, unknown>;
  code: string;
}) {
  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Spec
            <Tooltip content="The typed hypothesis: universe, horizon, named features, composable entry/exit modules, risk rules, and the fitted param space. No magic numbers — thresholds are fit from data." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SpecView spec={spec} params={params} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Compiled code
            <Tooltip content="The deterministic code this Version's spec compiled to — what actually runs in the backtest and track." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {code ? (
            <pre className="max-h-[420px] overflow-auto rounded-md border border-border/60 bg-background/60 p-3 font-mono text-[12px] leading-relaxed text-iris-soft">
              {code}
            </pre>
          ) : (
            <EmptyState title="No compiled code." hint="The compiled artifact appears here once this Version's spec has been compiled." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Notes tab: the agent's authoring / post-mortem rationale. ──
function NotesTab({ notes }: { notes: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <ScrollText className="size-4 text-iris-soft" /> Agent notes
          <Tooltip content="The authoring/post-mortem notes the agent recorded for this Version — why it was tried, and what was learned." />
        </CardTitle>
      </CardHeader>
      <CardContent>
        {notes ? (
          <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-muted">{notes}</div>
        ) : (
          <EmptyState title="No notes recorded." hint="The agent's rationale and post-mortem for this Version appear here when present." />
        )}
      </CardContent>
    </Card>
  );
}
