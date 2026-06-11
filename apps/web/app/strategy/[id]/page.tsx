import { ScrollText } from "lucide-react";
import { engineConfigured, getStrategy } from "../../data";
import type { Backtest, Execution, Point } from "@cosmu/contracts-ts";
import { LaunchLiveButton } from "@/components/live/launch-live-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TvChart } from "@/components/charts/tv-chart";
import { FoldBars } from "@/components/charts/fold-bars";
import { ChartEmpty } from "@/components/charts/chart-kit";
import { SpecView } from "@/components/strategy/spec-view";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { StrategyHeader } from "@/components/strategies/strategy-header";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { Tabs, type TabItem, InterlockStrip, type Interlock, GaugeBar } from "@/components/ui/viz";
import { cn, formatUsd } from "@/lib/utils";

// The REAL deterministic Gate thresholds (apps/engine/cosmu/config/settings.py). Surfaced here so the
// verdict reads as a set of pass/fail interlocks against the SAME numbers the engine gates on — never
// hand-picked display thresholds.
const GATE = { minTrades: 30, maxDrawdownPct: 0.25, maxPbo: 0.5, minDeflatedSharpe: 0 } as const;

// Turn a backtest into the four measurable Gate interlocks (the deterministic criteria the engine
// applies). Each chip carries the REAL measured value and the threshold it was judged against, so the
// operator sees exactly which gate held and which broke. Honest by construction — pure data, no fabrication.
function interlocksOf(bt: Backtest): Interlock[] {
  return [
    {
      label: "Deflated Sharpe",
      value: bt.deflated_sharpe.toFixed(2),
      threshold: `> ${GATE.minDeflatedSharpe.toFixed(0)}`,
      pass: bt.deflated_sharpe > GATE.minDeflatedSharpe
    },
    {
      label: "PBO",
      value: bt.pbo.toFixed(2),
      threshold: `< ${GATE.maxPbo.toFixed(2)}`,
      pass: bt.pbo < GATE.maxPbo
    },
    {
      label: "Max DD",
      value: `${(bt.max_dd * 100).toFixed(1)}%`,
      threshold: `< ${(GATE.maxDrawdownPct * 100).toFixed(0)}%`,
      pass: bt.max_dd < GATE.maxDrawdownPct
    },
    {
      label: "Trades",
      value: String(bt.num_trades),
      threshold: `≥ ${GATE.minTrades}`,
      pass: bt.num_trades >= GATE.minTrades
    }
  ];
}

// Derive a sim equity curve from the strategy's trade log: cumulative realized cash flow
// (sells add, buys subtract, fees always subtract), seeded at 0. Honest — built only from the
// real trades the engine returned; no fabricated track record.
function simCurveFromTrades(trades: Execution[]): Point[] {
  if (trades.length < 2) return [];
  let acc = 0;
  return trades.map((t) => {
    const gross = t.side === "sell" ? t.qty * t.price : -t.qty * t.price;
    acc += gross - t.fee;
    return { ts: t.ts, value: acc };
  });
}

// Render a free-form holdout record (e.g. {passed, deflated_sharpe, seen_once}) as labelled rows.
// The contract types holdout as Record<string, unknown>; format known number/bool shapes nicely.
function holdoutRows(holdout: Record<string, unknown>): { label: string; value: string; tone?: "up" | "down" }[] {
  return Object.entries(holdout).map(([k, v]) => {
    const label = k.replace(/_/g, " ");
    if (typeof v === "boolean") return { label, value: v ? "yes" : "no", tone: v ? "up" : "down" };
    if (typeof v === "number") return { label, value: v.toFixed(2) };
    return { label, value: String(v) };
  });
}

// Pull the glanceable summary off the REAL detail fields: thesis (spec.rationale), venue + timeframe
// (spec.universe / spec.horizon), and the best OOS return across passed backtests (else any backtest).
// Everything is defensive — the spec is typed Record<string, unknown>, so unknown shapes yield null and
// the header simply omits that chip rather than fabricating a value.
function strategySummary(
  spec: Record<string, unknown>,
  backtests: Backtest[]
): { thesis: string | null; venue: string | null; timeframe: string | null; bestOos: number | null } {
  const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
  const universe = isRecord(spec.universe) ? spec.universe : null;
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const venues = universe && Array.isArray(universe.venues) ? (universe.venues as unknown[]).filter((x): x is string => typeof x === "string") : [];
  const tfRaw = horizon && (typeof horizon.timeframe === "string" ? horizon.timeframe : null);
  // Prefer a passed backtest's OOS return; otherwise the highest OOS across all backtests. null when none.
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

// Strategy detail is the DEFINITIVE inspect view for one Version: the spec (named features, params,
// composable modules), the compiled code, the full trade blotter, the OOS/holdout + per-fold
// evidence, and the agent post-mortem/notes. All from the existing strategy detail endpoint —
// nothing fabricated; honest empty states throughout.
export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { strategy, connected } = await getStrategy(id);
  const simCurve = simCurveFromTrades(strategy.trades);

  if (!connected || !strategy.version_id) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
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

  const holdout = holdoutRows(strategy.holdout as Record<string, unknown>);

  // Glanceable summary, derived from REAL detail fields (no fabrication): the gate verdict from the
  // backtests, venue/timeframe/thesis from the spec, and an honest paper-vs-backtest read so the
  // detail header answers "is this proven, where does it trade, and on what edge?" at a glance.
  const passed = strategy.backtests.some((bt: Backtest) => bt.passed_gates);
  const summary = strategySummary(strategy.spec, strategy.backtests);
  // The representative backtest for the headline interlock strip: prefer a passed one, else the strongest
  // by deflated Sharpe (so the strip reflects the best honest evidence this Version has produced).
  const headlineBt =
    strategy.backtests.find((bt) => bt.passed_gates) ??
    [...strategy.backtests].sort((a, b) => b.deflated_sharpe - a.deflated_sharpe)[0] ??
    null;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <StrategyStages />

      {/* ONE title block — the verdict, the name, the lane, the thesis, and the honest headline number.
          No back-arrow, no redundant badge stack (the lean bar): the stage strip above IS the nav back. */}
      <StrategyHeader
        name={strategy.name}
        versionId={strategy.version_id}
        passed={passed}
        lane={[summary.venue, summary.timeframe]}
        thesis={summary.thesis}
        bestOos={summary.bestOos}
        action={passed ? <LaunchLiveButton versionId={strategy.version_id} strategyName={strategy.name} /> : undefined}
      />

      {/* Gate interlock strip — the verdict as pass/fail chips against the REAL deterministic thresholds,
          not a wall of numbers. Each chip shows the measured value and the bar it cleared (or didn't). */}
      {headlineBt ? (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-quiet">
            Gate interlocks
            <Tooltip content="The deterministic Gate's pass/fail criteria, evaluated on the strongest backtest: deflated Sharpe > 0, PBO < 0.50, max drawdown < 25%, and at least 30 trades. Green = cleared, red = blocked." />
          </div>
          <InterlockStrip interlocks={interlocksOf(headlineBt)} />
        </div>
      ) : null}

      {/* Tabbed progressive disclosure — the digestible default (Performance) opens first; Gate, Trades,
          Spec, and Notes are a tap away. Only the active panel is mounted in the DOM, so the page reads
          as one focused view instead of the old "expand to dump every section at once" wall. */}
      <Tabs
        ariaLabel="Strategy detail sections"
        tabs={[
          { id: "performance", label: "Performance", content: <PerformanceTab strategy={strategy} simCurve={simCurve} trades={strategy.trades} holdout={holdout} /> },
          { id: "gate", label: "Gate", count: strategy.backtests.length, content: <GateTab backtests={strategy.backtests} /> },
          { id: "trades", label: "Trades", count: strategy.trades.length, content: <TradesTab trades={strategy.trades} /> },
          { id: "spec", label: "Spec", content: <SpecTab spec={strategy.spec} params={strategy.params} code={strategy.generated_code} /> },
          { id: "notes", label: "Notes", content: <NotesTab notes={strategy.notes_md} /> }
        ] satisfies TabItem[]}
      />
    </div>
  );
}

// Costs, derived ONLY from the real trade fills (Execution.fee) — never fabricated. Total fees paid on
// this track, the per-trade average, and fees as a share of gross traded notional (the honest cost
// drag). Returns null when there are no fills, so the page shows an honest "nothing yet" instead.
function costsFromTrades(trades: Execution[]): { total: number; perTrade: number; pctOfNotional: number | null } | null {
  if (trades.length === 0) return null;
  let totalFee = 0;
  let notional = 0;
  for (const t of trades) {
    totalFee += t.fee;
    notional += Math.abs(t.qty * t.price);
  }
  return {
    total: totalFee,
    perTrade: totalFee / trades.length,
    pctOfNotional: notional > 0 ? (totalFee / notional) * 100 : null
  };
}

// ── Performance tab: the two faces of proof side by side — the Paper equity track (forward, built
// only from real fills) vs the out-of-sample backtest evidence by fold — plus the untouched holdout and
// an honest costs read. The default, digestible view. ──
function PerformanceTab({
  strategy,
  simCurve,
  trades,
  holdout
}: {
  strategy: { backtests: Backtest[] };
  simCurve: Point[];
  trades: Execution[];
  holdout: { label: string; value: string; tone?: "up" | "down" }[];
}) {
  const costs = costsFromTrades(trades);
  return (
    <div className="space-y-3">
      {/* Forward track vs backtest evidence — the two curves the operator weighs, side by side. */}
      <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Forward — Paper track
              <Tooltip content="Cumulative realized cash flow from this track's real paper fills (sells add, buys and fees subtract). This is forward proof on live data — built only from real trades, not a fabricated curve." />
            </CardTitle>
            <Badge variant="info">live data · no money</Badge>
          </CardHeader>
          <CardContent>
            {simCurve.length >= 2 ? (
              <TvChart points={simCurve} mode="sim" height={220} valueKind="usd" />
            ) : (
              <ChartEmpty title="No paper track yet" hint="The Paper equity curve renders once this track has at least two fills on live data." height={220} />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              Backtest — out-of-sample by fold
              <Tooltip content="Net return on each backtest fold (WFO, untouched holdout) — historical evidence the edge held out-of-sample. Green is positive OOS return, red negative. This is NOT paper performance." />
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <FoldBars backtests={strategy.backtests} height={180} />
            {/* Untouched holdout — the one-shot, seen-once test that gates promotion. */}
            <div className="space-y-1.5 border-t border-border/50 pt-3">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-quiet">
                Untouched holdout
                <Tooltip content="The one-shot, seen-once test. A Version may only meet its holdout once — passing it is what allows promotion." />
              </div>
              {holdout.length ? (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px]">
                  {holdout.map((row) => (
                    <div key={row.label} className="flex items-center justify-between">
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
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Costs — the real fee drag on this track, counted off the fills. Honest empty state when none. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Costs
            <Tooltip content="The fees this track has actually paid, counted off its real fills (Execution.fee). Net returns above are already after these costs — this card makes the drag explicit, never fabricated." />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {costs ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[12.5px] sm:grid-cols-3">
              <CostStat label="Total fees paid" value={formatUsd(costs.total, 2)} />
              <CostStat label="Avg fee / trade" value={formatUsd(costs.perTrade, 2)} />
              <CostStat
                label="Fees vs notional"
                value={costs.pctOfNotional !== null ? `${costs.pctOfNotional.toFixed(3)}%` : "—"}
              />
            </dl>
          ) : (
            <p className="text-[12px] text-quiet">No fills yet — costs appear here once this track trades.</p>
          )}
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

// ── Gate tab: every backtest's deterministic verdict, with a max-DD-vs-25%-limit gauge per card. ──
function GateTab({ backtests }: { backtests: Backtest[] }) {
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
              {/* Max-DD vs the 25% kill limit — the bar reads the headroom faster than the digits. */}
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

// ── Trades tab: the full fill log. Mounts only when opened (no cost on the default view). ──
function TradesTab({ trades }: { trades: Execution[] }) {
  if (trades.length === 0) {
    return (
      <Card>
        <CardContent className="pt-5">
          <EmptyState title="No trades yet." hint="Fills appear here as this track trades in Paper. Nothing is fabricated." />
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <THead>
            <TR>
              <TH className="pl-4 sticky-col">Side</TH>
              <TH className="text-right">Qty</TH>
              <TH className="text-right">Price</TH>
              <TH className="text-right">Fee</TH>
              <TH>Venue</TH>
              <TH className="pr-4">Time</TH>
            </TR>
          </THead>
          <TBody>
            {trades.map((trade) => (
              <TR key={trade.id}>
                <TD className="pl-4 sticky-col">
                  <Badge variant={trade.side === "buy" ? "up" : "down"}>{trade.side}</Badge>
                </TD>
                <TD className="text-right tabular text-foreground">{trade.qty}</TD>
                <TD className="text-right tabular text-foreground">{formatUsd(trade.price)}</TD>
                <TD className="text-right tabular text-muted">{formatUsd(trade.fee)}</TD>
                <TD className="text-quiet">{trade.venue ?? "—"}</TD>
                <TD className="pr-4 text-quiet">
                  <time dateTime={trade.ts}>{new Date(trade.ts).toLocaleString("en-US")}</time>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
    </Card>
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
