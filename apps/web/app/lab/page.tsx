import { Activity, ArrowRight, ChevronRight, FlaskConical, Search, Skull } from "lucide-react";
import Link from "next/link";
import { getBrain, getEvents, getIntelligence, getPopulation, getInboxQueue, engineConfigured } from "../data";
import type { FunnelStats } from "../data";
import type { GraveyardRow } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { FarmConsole } from "@/components/research/farm-console";
import { EdgeGate } from "@/components/research/edge-gate";
import { CrossAssetGate } from "@/components/research/cross-asset-gate";
import { ResearchBrain } from "@/components/research/research-brain";
import { GateFunnel, SurvivalDistribution } from "@/components/charts/brain-charts";
import { ActivityTimeline } from "@/components/observability/activity-timeline";
import { Tooltip } from "@/components/ui/tooltip";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import { IdeaInbox } from "@/components/overview/idea-inbox";
import { MetricCard, Tabs } from "@/components/ui/viz";
import { DataPreview } from "@/components/ui/data-preview";
import { cn, formatPct } from "@/lib/utils";

export default async function LabPage() {
  const [
    { population, connected },
    { brain, connected: brainConnected },
    { events, connected: evtConnected },
    { intelligence, connected: intelConnected },
    { items: inboxItems, connected: inboxConnected }
  ] = await Promise.all([getPopulation(), getBrain(), getEvents(), getIntelligence(), getInboxQueue()]);

  const anyConnected = connected || brainConnected;

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-8 lg:px-7">
      <SectionHeader
        eyebrow="lab"
        title="What is the machine discovering?"
        aside={<Badge variant="muted">LLM proposes · Gate disposes</Badge>}
      />

      <StrategyStages />

      {!anyConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* Next step nudge — surfaces when Gate survivors exist so the operator knows to check Backtest. */}
      {connected && population.forward_test > 0 && (
        <Link
          href="/strategies"
          className="flex items-center justify-between gap-3 rounded-lg border border-up/30 bg-up/[0.06] px-4 py-3 text-[12.5px] text-muted transition-colors hover:bg-up/10 hover:text-foreground"
        >
          <span>
            <span className="font-medium text-foreground">{population.forward_test}</span> version
            {population.forward_test !== 1 ? "s" : ""} cleared the Gate — review them in Backtest
          </span>
          <ChevronRight className="size-4 shrink-0 text-up" />
        </Link>
      )}

      {/* PRIMARY ACTION — the vibe loop: queue a vibe; the next tick authors a typed spec; the Gate rules.
          The full loop (queued → authored → Gate verdict) is visible in one place. */}
      <section className="space-y-3">
        <SectionHeader
          eyebrow="start here"
          title={<span className="text-base">Vibe loop — idea → spec → verdict</span>}
        />
        <IdeaInbox initial={inboxItems} connected={inboxConnected} configured={engineConfigured} />
      </section>

      {/* KPIs — the population at a glance. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="Versions tested" value={connected ? population.total : "—"} tone="iris" />
        <MetricCard label="In simulation" value={connected ? population.forward_test : "—"} tone="up" />
        <MetricCard label="In graveyard" value={connected ? population.killed : "—"} tone="down" />
        <MetricCard
          label="Kill rate"
          value={connected && population.total ? formatPct(population.kill_rate * 100, 1) : "—"}
          tone="warn"
        />
      </div>

      {/* Pipeline funnel — full lifecycle from intelligence data */}
      {intelConnected && intelligence.funnel.authored > 0 && (
        <section className="space-y-3">
          <SectionHeader
            eyebrow="pipeline"
            title={
              <span className="flex items-center gap-1.5 text-base">
                Funnel
                <Tooltip content="The full lifecycle: authored → Backtest → gate-passed → Simulation → Live, with how many were killed at each stage." />
              </span>
            }
          />
          <Card>
            <CardContent className="pt-5">
              <PipelineFunnel funnel={intelligence.funnel} />
            </CardContent>
          </Card>
        </section>
      )}

      {/* SECONDARY DETAIL — brain, the gates, the finder, activity and graveyard. One focused tab at a
          time (replaces a single mega "show more" that dumped every section at once). */}
      <section className="space-y-3">
        <SectionHeader eyebrow="detail" title={<span className="text-base">Brain, gates &amp; graveyard</span>} />
        <Tabs
          ariaLabel="Lab detail"
          defaultTab="gates"
          tabs={[
            {
              id: "gates",
              label: (
                <span className="flex items-center gap-1.5">
                  <FlaskConical className="size-3.5" /> Is there an edge?
                </span>
              ),
              content: (
                <div className="grid gap-3">
                  <EdgeGate />
                  <CrossAssetGate />
                </div>
              ),
            },
            {
              id: "brain",
              label: "Research brain",
              content: brainConnected ? (
                <div className="space-y-3">
                  <div className="grid gap-3 lg:grid-cols-2">
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-1.5">
                          Gate funnel
                          <Tooltip content="Every generated Version runs the deterministic Gate. Most are killed — the funnel shows how many survive." />
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <GateFunnel gated={brain.gated} />
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-1.5">
                          Survival distribution
                          <Tooltip content="Each survivor's score — the model's estimate the edge persists. It only orders the queue; never vetoes." />
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <SurvivalDistribution survivors={brain.survivors} />
                      </CardContent>
                    </Card>
                  </div>
                  <ResearchBrain brain={brain} />
                </div>
              ) : (
                <Card>
                  <CardContent className="py-10 text-center text-[12.5px] text-muted">
                    The research brain appears once the engine is connected. No demo data is shown.
                  </CardContent>
                </Card>
              ),
            },
            {
              id: "finder",
              label: (
                <span className="flex items-center gap-1.5">
                  <Search className="size-3.5" /> Strategy finder
                </span>
              ),
              content: <FarmConsole />,
            },
            {
              id: "activity",
              label: (
                <span className="flex items-center gap-1.5">
                  <Activity className="size-3.5" /> Activity
                </span>
              ),
              content:
                evtConnected && events.length > 0 ? (
                  <Card>
                    <CardContent className="pt-4">
                      <ActivityTimeline events={events} />
                    </CardContent>
                  </Card>
                ) : (
                  <Card>
                    <CardContent className="py-10 text-center text-[12.5px] text-muted">
                      No recent activity yet. Events appear here as the machine works.
                    </CardContent>
                  </Card>
                ),
            },
            {
              id: "graveyard",
              label: (
                <span className="flex items-center gap-1.5">
                  <Skull className="size-3.5" /> Graveyard
                </span>
              ),
              count: connected ? population.killed : undefined,
              content:
                connected && population.killed > 0 ? (
                  <div className="grid gap-3 lg:grid-cols-[1fr_1.6fr]">
                    <Card>
                      <CardHeader>
                        <CardTitle>By origin</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {Object.entries(population.by_lane).map(([lane, raw]) => {
                          const n = Number(raw);
                          const pct = population.total ? (n / population.total) * 100 : 0;
                          return (
                            <div key={lane} className="space-y-1.5">
                              <div className="flex items-center justify-between text-[12.5px]">
                                <span className="capitalize text-foreground">{lane}</span>
                                <span className="tabular text-muted">{n}</span>
                              </div>
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                                <div className="h-full rounded-full bg-iris/75" style={{ width: `${Math.max(pct, 2)}%` }} />
                              </div>
                            </div>
                          );
                        })}
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader>
                        <CardTitle>Recent deaths</CardTitle>
                        <Badge variant="down">with kill reasons</Badge>
                      </CardHeader>
                      <CardContent>
                        <DataPreview href="/strategies" viewAllLabel="View all strategies" total={population.killed}>
                          <div className="space-y-2">
                            {population.graveyard.slice(0, 5).map((row: GraveyardRow) => (
                              <div
                                key={row.version_id}
                                className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                              >
                                <div className="min-w-0">
                                  <div className="truncate text-[12.5px] font-medium text-foreground">{row.name}</div>
                                  <div className="text-[11px] text-quiet">{row.origin}</div>
                                </div>
                                <div className="flex flex-wrap justify-end gap-1">
                                  {row.kill_reason.split(",").map((r) => (
                                    <Badge key={r} variant="down">
                                      {r.replace(/_/g, " ")}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </DataPreview>
                      </CardContent>
                    </Card>
                  </div>
                ) : (
                  <Card>
                    <CardContent className="py-10 text-center text-[12.5px] text-muted">
                      Nothing in the graveyard yet — no version has been killed.
                    </CardContent>
                  </Card>
                ),
            },
          ]}
        />
      </section>
    </div>
  );
}

const PIPELINE_STAGES: { key: keyof FunnelStats; label: string; tone: string }[] = [
  { key: "authored", label: "Authored", tone: "text-foreground" },
  { key: "screened", label: "Screened", tone: "text-iris-soft" },
  { key: "gate_passed", label: "Gate passed", tone: "text-up" },
  { key: "funded", label: "Funded", tone: "text-up" },
  { key: "live", label: "Live", tone: "text-info" },
];

function PipelineFunnel({ funnel }: { funnel: FunnelStats }) {
  const max = Math.max(funnel.authored, 1);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        {PIPELINE_STAGES.map((stage, i) => {
          const count = funnel[stage.key];
          const widthPct = Math.max((count / max) * 100, 4);
          return (
            <div key={stage.key} className="flex min-w-0 flex-1 items-center gap-1.5">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center justify-between text-[10.5px]">
                  <span className="font-semibold uppercase tracking-wide text-quiet">{stage.label}</span>
                  <span className={cn("tabular font-semibold", stage.tone)}>{count}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      stage.key === "live" ? "bg-info" : stage.key === "gate_passed" || stage.key === "funded" ? "bg-up" : "bg-iris/70"
                    )}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
              {i < PIPELINE_STAGES.length - 1 && <ArrowRight className="mt-3 size-3 shrink-0 text-quiet/40" />}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-4 text-[11px]">
        <span className="flex items-center gap-1.5 text-down">
          <span className="tabular font-semibold">{funnel.killed}</span> killed
        </span>
        {funnel.authored > 0 && (
          <span className="text-warn">kill rate {formatPct((funnel.killed / funnel.authored) * 100, 1)}</span>
        )}
        {funnel.gate_passed > 0 && funnel.authored > 0 && (
          <span className="text-quiet">gate pass rate {formatPct((funnel.gate_passed / funnel.authored) * 100, 1)}</span>
        )}
      </div>
    </div>
  );
}
