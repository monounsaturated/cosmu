// Overview — the operator's CONTROL ROOM. Answers the only two questions that matter, in five seconds:
//   (1) Is the machine making money?  → the hero figure (live simulation net P&L, net of fees) + the real
//       equity curve, with an honest "$0 · no funded tracks yet" day-0 state.
//   (2) Does it need me?              → the "Needs you" queue (human-only decisions) beside the recent
//       machine activity feed.
//
// HIERARCHY (premium, lean, intuitive): the page reads top-to-bottom as ANSWER → CONTEXT.
//   • THE ANSWER  — hero figure, the four glanceable KPIs, then "Needs you" beside "Recent activity".
//                   Everything the operator needs to decide "leave it running" or "step in" is above the
//                   fold, at the highest visual weight.
//   • THE DETAIL  — one labelled section, progressively disclosed via tabs (pipeline · verdicts ·
//                   simulation · data), so the supporting context is one focused panel at a time instead
//                   of a long wall of equal-weight cards.
//
// HONESTY (the machine that never lies): when the engine is unreachable we render a single "not connected"
// state and never fabricate. Every number on this page is real engine data passed through {data, connected}.

import type { ReactNode } from "react";
import { ArrowRight, ClipboardCheck, FlaskConical, LineChart, Users } from "lucide-react";
import Link from "next/link";
import {
  engineConfigured,
  getAutonomyStatus,
  getEvents,
  getExperiments,
  getInboxQueue,
  getLeaderboard,
  getIntelligence,
  getOverview,
  getRecommendations
} from "./data";
import type { ExperimentTheory, FunnelStats } from "./data";
import type { InboxQueueItem, LeaderboardRow } from "@cosmu/contracts-ts";
import { IdeaIntake } from "@/components/overview/idea-intake";
import { MoneyHero } from "@/components/overview/money-hero";
import { KpiRow } from "@/components/overview/kpi-row";
import { NeedsYouCard, RecentActivityCard } from "@/components/overview/control-room";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DataPreview } from "@/components/ui/data-preview";
import { Tooltip } from "@/components/ui/tooltip";
import { Tabs } from "@/components/ui/viz";
import { DataFreshness } from "@/components/overview/data-freshness";
import { cn, timeAgo } from "@/lib/utils";

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
    { overview, connected: overviewConnected },
    { items: recommendations, connected: recConnected },
    { events, connected: eventsConnected }
  ] = await Promise.all([
    getAutonomyStatus(),
    getExperiments(),
    getInboxQueue(),
    getLeaderboard(),
    getIntelligence(),
    getOverview(),
    getRecommendations(),
    getEvents()
  ]);

  const connected =
    statusConnected ||
    experimentsConnected ||
    lbConnected ||
    intelConnected ||
    inboxConnected ||
    overviewConnected ||
    recConnected ||
    eventsConnected;

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <Header />
        <NotConnected
          configured={engineConfigured}
          what="The Overview shows whether the machine is making money and whether it needs you — the live simulation P&L, what's waiting for your call, the candidate pipeline, the Gate's verdicts, and data freshness. Connect the engine to see real data; nothing is fabricated."
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

  // Tab counts — every one a real engine count, so the labels never overstate what is there.
  const inSimCount = simRows.length;
  const verdictCount = theories.length;
  const freshCount = intelligence.data_freshness.length;

  return (
    <div className="mx-auto max-w-[1100px] space-y-8 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <Header />

      {/* ── THE ANSWER ─────────────────────────────────────────────────────────────────────────────── */}

      {/* (1) IS IT MAKING MONEY — the one hero figure (live sim net P&L, net of fees) + the real equity
          curve + machine-state chip. Honest day-0 / offline states; the single chart on the page. */}
      <MoneyHero
        overview={overview}
        overviewConnected={overviewConnected}
        status={status}
        statusConnected={statusConnected}
      />

      {/* The four glanceable KPIs — survivors, tracks in simulation, days to live-ready, Gate verdicts. */}
      <KpiRow
        funnel={intelligence.funnel}
        intelConnected={intelConnected}
        simRows={simRows}
        lbConnected={lbConnected}
        summary={experiments.summary}
        experimentsConnected={experimentsConnected}
      />

      {/* (2) DOES IT NEED ME — the human-only decision queue beside the live activity feed. */}
      <section className="grid gap-6 lg:grid-cols-2">
        <NeedsYouCard recommendations={recommendations} connected={recConnected} configured={engineConfigured} />
        <RecentActivityCard events={events} connected={eventsConnected} />
      </section>

      {/* ── THE DETAIL ─────────────────────────────────────────────────────────────────────────────── */}
      {/* One labelled section, progressively disclosed: the supporting context behind the answer above,
          one focused panel at a time instead of four equal-weight cards stacked into a wall. */}
      <section className="space-y-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">the detail</div>
          <h2 className="mt-1.5 text-lg font-semibold tracking-tight text-foreground">How the machine got here</h2>
          <p className="mt-1 text-[12.5px] text-muted">
            The pipeline that produces the figure above — idea to spec to Gate to simulation. Every number real.
          </p>
        </div>

        <Tabs
          ariaLabel="Supporting context"
          tabs={[
            {
              id: "pipeline",
              label: "Pipeline",
              content: (
                <Card className="p-5">
                  <CandidatePipeline
                    funnel={intelligence.funnel}
                    inboxItems={inboxItems}
                    inboxConnected={inboxConnected}
                    intelConnected={intelConnected}
                  />
                </Card>
              )
            },
            {
              id: "verdicts",
              label: "Verdicts",
              count: verdictCount,
              content: (
                <Card className="p-5">
                  <TheoriesLedger theories={theories} connected={experimentsConnected} />
                </Card>
              )
            },
            {
              id: "simulation",
              label: "In simulation",
              count: inSimCount,
              content: (
                <Card className="p-5">
                  <ForwardTestWindow rows={simRows} connected={lbConnected} />
                </Card>
              )
            },
            {
              id: "data",
              label: "Data",
              count: freshCount,
              content: (
                <Card className="p-5">
                  <DataFreshness sources={intelligence.data_freshness} connected={intelConnected} />
                </Card>
              )
            }
          ]}
        />
      </section>
    </div>
  );
}

function Header() {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">overview</div>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">The machine</h1>
      <p className="mt-1 text-[13px] text-muted">
        Is it making money, and does it need you? Everything below is real — nothing fabricated.
      </p>
    </div>
  );
}

// A lightweight panel head used inside the tabbed detail section — gives each panel a title + one-line
// description without the full Card chrome (the Tabs panel already provides the frame).
function PanelHead({ icon, title, sub }: { icon: ReactNode; title: ReactNode; sub: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-foreground">
        <span className="text-iris-soft">{icon}</span>
        {title}
      </div>
      <p className="mt-1 text-[12px] text-quiet">{sub}</p>
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
    <div>
      <PanelHead
        icon={<FlaskConical className="size-4" />}
        title="Candidate pipeline"
        sub="idea → spec → Gate → simulation"
      />
      <div className="space-y-4">
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
      </div>
    </div>
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
    <div>
      <PanelHead
        icon={<ClipboardCheck className="size-4" />}
        title={
          <span className="flex items-center gap-1.5">
            Theories
            {/* Cohort tooltip — beside the title so the operator sees it alongside PASS/FAIL counts */}
            <Tooltip
              content="Specs are tested as a cohort. The Gate's BH-FDR correction means a PASS isn't just lucky — it survived multiple-testing scrutiny alongside every other spec in the same batch."
              side="bottom"
            />
          </span>
        }
        sub={`${theories.length} theor${theories.length === 1 ? "y" : "ies"} ruled on · PASS or FAIL`}
      />
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
    </div>
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
    <div>
      <PanelHead
        icon={<LineChart className="size-4" />}
        title="In simulation"
        sub="Cleared Gate · live bars · no capital"
      />
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
    </div>
  );
}
