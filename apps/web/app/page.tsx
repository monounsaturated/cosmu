// Overview — the operator's command centre. Answers four questions in one glance:
//   (a) Is the machine running and in what mode?
//   (b) What candidates are in the pipeline, and how has the Gate ruled?
//   (c) Which strategies are in forward test, and how many days have elapsed?
//   (d) Is the data feed fresh?
// HONEST: when the engine is unreachable we render a single "not connected" state and never fabricate.

import { Activity, ArrowRight, ClipboardCheck, FlaskConical, LineChart, Pause, Play, TrendingUp, Users } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getAutonomyStatus, getExperiments, getInboxQueue, getLeaderboard, getIntelligence, getOverview } from "./data";
import type { ExperimentTheory, ExperimentsResponse } from "./data";
import type { InboxQueueItem, LeaderboardRow, OverviewResponse } from "@cosmu/contracts-ts";
import type { FunnelStats } from "./data";
import { IdeaIntake } from "@/components/overview/idea-intake";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DataPreview } from "@/components/ui/data-preview";
import { Tooltip } from "@/components/ui/tooltip";
import { MetricCard, Sparkline } from "@/components/ui/viz";
import { DataFreshness } from "@/components/overview/data-freshness";
import { cn, formatUsd, timeAgo } from "@/lib/utils";

// Live operator dashboard: always render on-demand with fresh engine data — never statically pre-render.
// (Static export hangs fetching the engine at build time; on-demand also lets the honest "not connected"
// state handle an unreachable engine gracefully instead of failing the build.)
export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [
    { status, connected: statusConnected },
    { experiments, connected: experimentsConnected },
    { items: inboxItems, connected: inboxConnected },
    { leaderboard, connected: lbConnected },
    { intelligence, connected: intelConnected },
    { overview, connected: overviewConnected }
  ] = await Promise.all([
    getAutonomyStatus(),
    getExperiments(),
    getInboxQueue(),
    getLeaderboard(),
    getIntelligence(),
    getOverview()
  ]);

  const connected = statusConnected || experimentsConnected || lbConnected || intelConnected || inboxConnected || overviewConnected;

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <Header />
        <NotConnected
          configured={engineConfigured}
          what="The Overview shows the machine's status, the candidate pipeline, Gate-ruled theories, forward-test progress, and data freshness. Connect the engine to see real data; nothing is fabricated."
        />
      </div>
    );
  }

  const theories: ExperimentTheory[] = experiments.theories ?? [];
  const allLbRows = leaderboard.rows as LeaderboardRow[];
  const simRows = allLbRows.filter((r) => {
    const s = (r.status ?? "").toLowerCase();
    return s === "forward_test" || s === "forward" || s === "paper";
  });

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <Header />

      {/* Command-center metric strip — the four glanceable headline numbers, with the REAL sim equity
          sparkline. Honest day-0 states when the engine has produced no curve / verdicts yet. */}
      <CommandStrip
        overview={overview}
        overviewConnected={overviewConnected}
        funnel={intelligence.funnel}
        intelConnected={intelConnected}
        summary={experiments.summary}
        experimentsConnected={experimentsConnected}
      />

      <MachineStatus status={status} connected={statusConnected} />

      {/* Candidate pipeline — idea → spec → Gate, with cohort context. */}
      <CandidatePipeline
        funnel={intelligence.funnel}
        inboxItems={inboxItems}
        inboxConnected={inboxConnected}
        intelConnected={intelConnected}
      />

      {/* Theories — every Gate ruling, PASS or FAIL, drawn from the same experiment memory the
          /verdicts page renders, so "View all" is a true drill-down. */}
      <TheoriesLedger theories={theories} connected={experimentsConnected} />

      {/* Forward-test window — strategies in simulation with days elapsed. */}
      <ForwardTestWindow rows={simRows} connected={lbConnected} />

      {/* Data coverage — per-source freshness so the operator knows the feed is alive. */}
      <DataFreshness sources={intelligence.data_freshness} connected={intelConnected} />
    </div>
  );
}

function Header() {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">overview</div>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">The machine</h1>
      <p className="mt-1 text-[13px] text-muted">Pipeline status, Gate verdicts, forward-test progress, and data coverage — all real, nothing fabricated.</p>
    </div>
  );
}

// Command-center metric strip — four dense KPI tiles. Every number is REAL engine data; the sim-equity
// sparkline is the actual /overview equity_curve (renders nothing, with an honest "day 0" hint, until the
// engine has produced ≥2 points). The Gate pass-rate is computed from the same experiment memory the
// Theories card and /verdicts page render, so the headline and the drill-down never disagree.
function CommandStrip({
  overview,
  overviewConnected,
  funnel,
  intelConnected,
  summary,
  experimentsConnected
}: {
  overview: OverviewResponse;
  overviewConnected: boolean;
  funnel: FunnelStats;
  intelConnected: boolean;
  summary: ExperimentsResponse["summary"];
  experimentsConnected: boolean;
}) {
  const curve = overview.equity_curve ?? [];
  const equityValues = curve.map((p) => p.value);
  const hasCurve = equityValues.length >= 2;
  const pnl = overview.pnl_net;

  // Gate pass-rate over the real ruled theories (passed ÷ total). Honest "—" when nothing has been ruled.
  const ruled = summary.total;
  const passes = summary.passed;
  const passRate = ruled > 0 ? Math.round((passes / ruled) * 100) : null;

  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Sim net P&L"
        tone={pnl > 0 ? "up" : pnl < 0 ? "down" : "iris"}
        icon={<TrendingUp className="size-4" />}
        value={overviewConnected ? <span className={pnl >= 0 ? "text-up" : "text-down"}>{formatUsd(pnl)}</span> : "—"}
        hint={overviewConnected ? (hasCurve ? "across all sim tracks" : "day 0 — no curve yet") : "engine offline"}
        visual={hasCurve ? <Sparkline values={equityValues} ariaLabel="simulation equity trend" /> : undefined}
      />
      <MetricCard
        label="Passed Gate"
        tone="up"
        icon={<ClipboardCheck className="size-4" />}
        value={intelConnected ? funnel.gate_passed : "—"}
        hint={intelConnected ? `${funnel.authored} authored · ${funnel.killed} killed` : "engine offline"}
      />
      <MetricCard
        label="In simulation"
        tone="iris"
        icon={<FlaskConical className="size-4" />}
        value={intelConnected ? funnel.funded : "—"}
        hint={intelConnected ? `${funnel.live} live` : "engine offline"}
      />
      <MetricCard
        label="Gate pass-rate"
        tone={passRate === null ? "muted" : passRate >= 20 ? "up" : "warn"}
        icon={<Users className="size-4" />}
        value={experimentsConnected && passRate !== null ? `${passRate}%` : "—"}
        hint={experimentsConnected ? (ruled > 0 ? `${passes}/${ruled} theories passed` : "none ruled yet") : "ledger offline"}
      />
    </section>
  );
}

function MachineStatus({
  status,
  connected
}: {
  status: Awaited<ReturnType<typeof getAutonomyStatus>>["status"];
  connected: boolean;
}) {
  const running = connected && status.running && !status.paused;
  const stateLabel = !connected ? "Unknown" : status.paused ? "Paused" : status.running ? "Running" : "Idle";
  const stateVariant = running ? "up" : status.paused ? "warn" : "muted";
  const modeLabel = status.live_enabled ? "Live" : "Simulation";
  const lastTick = timeAgo(status.last_tick_at);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Activity className="size-4 text-iris-soft" /> Machine status
        </CardTitle>
        <div className="flex items-center gap-1.5">
          <Badge variant={stateVariant}>
            {running ? <Play className="size-3" /> : status.paused ? <Pause className="size-3" /> : null}
            {stateLabel}
          </Badge>
          <Badge variant={status.live_enabled ? "info" : "muted"}>{modeLabel}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          <Field label="Mode" value={modeLabel} />
          <Field label="Last tick" value={lastTick ?? "—"} />
          <Field label="Cycles run" value={connected ? String(status.cycles_run) : "—"} />
        </div>
        {connected && status.next_action ? (
          <p className="mt-4 text-[12px] text-muted">
            <span className="text-quiet">Next: </span>
            {status.next_action}
          </p>
        ) : null}
        {!connected ? (
          <p className="mt-4 text-[12px] text-quiet">Status unknown — the engine did not report. The verdict ledger below is read from disk.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">{label}</div>
      <div className="mt-1 text-[15px] font-semibold tabular text-foreground">{value}</div>
    </div>
  );
}

// Candidate pipeline — shows the search funnel (authored → passed Gate → in simulation) with
// a dump box so the operator can feed the machine new ideas inline.
function CandidatePipeline({
  funnel,
  inboxItems,
  inboxConnected,
  intelConnected
}: {
  funnel: FunnelStats;
  inboxItems: InboxQueueItem[];
  inboxConnected: boolean;
  intelConnected: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <FlaskConical className="size-4 text-iris-soft" /> Candidate pipeline
        </CardTitle>
        <span className="text-[12px] text-quiet">idea → spec → Gate → simulation</span>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Pipeline funnel stats */}
        {intelConnected && (funnel.authored > 0 || funnel.gate_passed > 0) ? (
          <PipelineFunnelBar funnel={funnel} />
        ) : null}

        {/* Idea intake — queue a new idea inline (bare variant; the queue is shown below). */}
        <div>
          <div className="mb-2 text-[11.5px] font-medium text-quiet">Queue a new idea</div>
          <IdeaIntake variant="bare" />
        </div>

        {/* Queue snapshot */}
        <IdeaQueuePreview items={inboxItems} connected={inboxConnected} />
      </CardContent>
    </Card>
  );
}

// Pipeline funnel viz: the candidate population narrowing through the lifecycle (authored → screened →
// passed Gate → funded → live), drawn as proportional bars so the survivorship narrows visibly. Each
// stage's bar width is RELATIVE to the widest stage (authored) — the real counts are the source of truth.
// The killed count is shown as the attrition tail. Honest: zero-width bars when a stage is empty.
const FUNNEL_STAGES: { key: keyof FunnelStats; label: string; tone: string }[] = [
  { key: "authored", label: "Specs authored", tone: "bg-border-strong" },
  { key: "screened", label: "Screened", tone: "bg-info/70" },
  { key: "gate_passed", label: "Passed Gate", tone: "bg-up/80" },
  { key: "funded", label: "In simulation", tone: "bg-iris/80" },
  { key: "live", label: "Live", tone: "bg-iris" }
];

function PipelineFunnelBar({ funnel }: { funnel: FunnelStats }) {
  const top = Math.max(funnel.authored, funnel.screened, funnel.gate_passed, funnel.funded, funnel.live, 1);
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-3.5 py-3">
      <div className="space-y-1.5">
        {FUNNEL_STAGES.map((stage) => {
          const value = funnel[stage.key];
          const pct = (value / top) * 100;
          return (
            <div key={stage.key} className="flex items-center gap-2.5">
              <div className="flex w-28 shrink-0 items-center gap-1 text-[11px] text-quiet">
                {stage.label}
                {stage.key === "gate_passed" ? (
                  <Tooltip
                    content="Specs are gated as a cohort — tested together — so the Gate's multiple-testing correction (BH-FDR) ensures a winner isn't just lucky from many tries."
                    side="bottom"
                  >
                    <Users className="size-3 text-quiet" />
                  </Tooltip>
                ) : null}
              </div>
              <div className="h-4 flex-1 overflow-hidden rounded bg-surface-2">
                <div
                  className={cn("h-full rounded transition-[width] duration-500", stage.tone)}
                  style={{ width: `${Math.max(pct, value > 0 ? 3 : 0)}%` }}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-[13px] font-semibold tabular text-foreground">{value}</span>
            </div>
          );
        })}
      </div>
      {funnel.killed > 0 ? (
        <div className="mt-2 border-t border-border/40 pt-2 text-[11px] text-quiet">
          <span className="text-down tabular font-medium">{funnel.killed}</span> killed / graveyarded along the way
        </div>
      ) : null}
    </div>
  );
}

// Compact snapshot of the idea queue — queued (waiting for next tick to author a spec) or imported
// (already turned into a typed StrategySpec, now flowing through Backtest → Gate). Server-rendered
// so the operator sees the real queue state on page load. No optimistic rows; never fabricated.
function IdeaQueuePreview({ items, connected }: { items: InboxQueueItem[]; connected: boolean }) {
  if (!connected || items.length === 0) return null;
  return (
    <div className="border-t border-border/50 pt-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">
          Queue — {items.length} idea{items.length === 1 ? "" : "s"}
        </span>
        <Link href="/lab" className="flex items-center gap-1 text-[11px] text-iris-soft hover:underline">
          See full Lab <ArrowRight className="size-3" />
        </Link>
      </div>
      <ul className="space-y-1.5">
        {items.slice(0, 4).map((item) => (
          <li
            key={item.filename}
            className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
          >
            <span className="min-w-0 truncate text-[12.5px] text-foreground">{item.name}</span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-[11px] text-quiet">{timeAgo(item.ts) ?? ""}</span>
              <Badge variant={item.status === "imported" ? "up" : "info"}>{item.status}</Badge>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const PREVIEW_N = 5;

// Theories — every Gate ruling, drawn from the SAME experiment memory the /verdicts page renders
// (GET /research/experiments) so "View all" is a true drill-down. PASS or FAIL, with the deflated-Sharpe
// the Gate measured so the operator knows exactly what decided each ruling.
function TheoriesLedger({ theories, connected }: { theories: ExperimentTheory[]; connected: boolean }) {
  const preview = theories.slice(0, PREVIEW_N);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <ClipboardCheck className="size-4 text-iris-soft" /> Theories
          {/* Cohort tooltip — in the header so the operator sees it alongside PASS/FAIL counts */}
          <Tooltip
            content="Specs are tested as a cohort. The Gate's BH-FDR correction means a PASS isn't just lucky — it survived multiple-testing scrutiny alongside every other spec in the same batch."
            side="bottom"
          />
        </CardTitle>
        <span className="text-[12px] text-quiet">{theories.length} theor{theories.length === 1 ? "y" : "ies"} ruled on</span>
      </CardHeader>
      <CardContent>
        {theories.length === 0 ? (
          <EmptyState
            title={connected ? "No theories yet" : "Theories unavailable"}
            hint={
              connected
                ? "Every theory the Gate rules on appears here — PASS or FAIL, with the stat that decided it."
                : "The engine did not return the experiment memory. Once it is up, real theories appear here."
            }
            icon={<ClipboardCheck className="size-5" />}
          />
        ) : (
          <DataPreview href="/verdicts" viewAllLabel="View all theories" total={theories.length}>
            <ul className="divide-y divide-border/60">
              {preview.map((t) => {
                const pass = t.decision === "PASS";
                const date = t.ts ? t.ts.slice(0, 10) : null;
                return (
                  <li key={t.run_id} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 py-3 first:pt-0 last:pb-0">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[13.5px] font-medium text-foreground">{t.hypothesis}</span>
                        {date ? <span className="text-[11px] text-quiet">{date}</span> : null}
                      </div>
                      <TheoryStats theory={t} />
                    </div>
                    <Badge variant={pass ? "up" : "down"} className={cn("mt-0.5 shrink-0")}>
                      {pass ? "PASS" : "FAIL"}
                    </Badge>
                  </li>
                );
              })}
            </ul>
          </DataPreview>
        )}
      </CardContent>
    </Card>
  );
}

// Surface the key stats so the operator knows what the Gate measured for a theory: the best in-sample
// deflated-Sharpe probability (the Gate's 0.95 bar), how many candidates were tested, and how many were
// promoted. Honest — only renders the numbers the engine actually returned.
function TheoryStats({ theory }: { theory: ExperimentTheory }) {
  const bits: string[] = [];
  if (theory.best_dsr !== null && theory.best_dsr !== undefined) {
    bits.push(`DSR-prob ${theory.best_dsr.toFixed(2)}`);
  }
  if (theory.n_candidates > 0) {
    bits.push(`${theory.n_candidates} candidate${theory.n_candidates === 1 ? "" : "s"}`);
  }
  if (theory.n_promoted > 0) {
    bits.push(`${theory.n_promoted} promoted`);
  }
  if (bits.length === 0) return null;
  return (
    <p className="mt-1 text-[11px] text-quiet">
      {bits.join(" · ")}
    </p>
  );
}

// Forward-test window — strategies that cleared the Gate and are now accumulating real-bar evidence.
// Shows days elapsed so the operator can see which are approaching the ≥30d readiness signal.
function ForwardTestWindow({ rows, connected }: { rows: LeaderboardRow[]; connected: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <LineChart className="size-4 text-iris-soft" /> In simulation
        </CardTitle>
        <span className="text-[12px] text-quiet">Cleared Gate · live bars · no capital</span>
      </CardHeader>
      <CardContent>
        {!connected ? (
          <EmptyState
            title="Engine not connected"
            hint="Simulation status appears here once the engine is connected."
            icon={<LineChart className="size-5" />}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No strategies in simulation yet"
            hint={
              <>
                Strategies move here automatically once they clear the Gate. Check the{" "}
                <Link href="/lab" className="text-iris-soft hover:underline">Lab</Link> to see where the pipeline stands.
              </>
            }
            icon={<LineChart className="size-5" />}
          />
        ) : (
          <DataPreview href="/forward-test" viewAllLabel="View all in simulation" total={rows.length}>
            <ul className="divide-y divide-border/60">
              {rows.slice(0, 5).map((r) => {
                const days = Math.floor(r.forward_age_days ?? 0);
                const ready = days >= 30;
                return (
                  <li key={r.version_id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                    <div className="min-w-0 flex-1">
                      <span className="text-[13px] font-medium text-foreground">{r.name}</span>
                      <span className="ml-2 text-[11px] text-quiet">{r.venue}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {/* Forward CLOCK only — never the backtest % dressed up as forward return. The forward
                          test is the clock since funding; a forward-return number isn't in the contract yet. */}
                      <span className="text-[11.5px] tabular text-quiet">{days < 1 ? "day 0" : `${days}d fwd`}</span>
                      <Badge variant={ready ? "up" : "muted"}>{ready ? "≥30d" : "maturing"}</Badge>
                    </div>
                  </li>
                );
              })}
            </ul>
          </DataPreview>
        )}
      </CardContent>
    </Card>
  );
}
