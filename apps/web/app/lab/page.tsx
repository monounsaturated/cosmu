import { Activity, ArrowRight } from "lucide-react";
import { getBrain, getEvents, getIntelligence, getPopulation, getInboxQueue, engineConfigured } from "../data";
import type { FunnelStats } from "../data";
import type { GraveyardRow } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { FarmConsole } from "@/components/research/farm-console";
import { EdgeGate } from "@/components/research/edge-gate";
import { CrossAssetGate } from "@/components/research/cross-asset-gate";
import { ResearchBrain } from "@/components/research/research-brain";
import { GateFunnel, SurvivalDistribution } from "@/components/charts/brain-charts";
import { ActivityTimeline } from "@/components/observability/activity-timeline";
import { Tooltip } from "@/components/ui/tooltip";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected, NotConnectedBanner } from "@/components/ui/honest-state";
import { IdeaInbox } from "@/components/overview/idea-inbox";
import { ExpandableSection } from "@/components/ui/expandable-section";
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
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="lab"
        title="What is the machine discovering?"
        aside={<Badge variant="muted">LLM proposes · Gate disposes</Badge>}
      />

      <StrategyStages />

      {!anyConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* Idea inbox — queue a vibe; the next tick authors a typed spec; the Gate rules.
          The full vibe loop (queued → authored → Gate verdict) is visible in one place. */}
      <section className="space-y-3">
        <h3 className="text-[13px] font-semibold text-foreground">Vibe loop — idea → spec → verdict</h3>
        <IdeaInbox
          initial={inboxItems}
          connected={inboxConnected}
          configured={engineConfigured}
        />
      </section>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Versions tested" value={connected ? population.total : "—"} accent="iris" />
        <Stat label="In simulation" value={connected ? population.forward_test : "—"} accent="up" />
        <Stat label="In graveyard" value={connected ? population.killed : "—"} accent="down" />
        <Stat label="Kill rate" value={connected && population.total ? formatPct(population.kill_rate * 100, 1) : "—"} accent="warn" />
      </div>

      {/* Pipeline funnel — full lifecycle from intelligence data */}
      {intelConnected && intelligence.funnel.authored > 0 && (
        <section className="space-y-3">
          <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
            Pipeline funnel
            <Tooltip content="The full lifecycle: authored → Backtest → gate-passed → Simulation → Live, with how many were killed at each stage." />
          </h3>
          <Card>
            <CardContent className="pt-5">
              <PipelineFunnel funnel={intelligence.funnel} />
            </CardContent>
          </Card>
        </section>
      )}

      {/* Progressive disclosure — digestible by default. Gate charts, brain detail, finder, activity
          and graveyard are secondary; show them on demand. */}
      <ExpandableSection
        showLabel="Show brain detail, gates, finder & graveyard"
        hideLabel="Hide detail"
        summary={null}
      >
        {/* Research brain: gate funnel + survivors */}
        {brainConnected && (
          <section className="space-y-3">
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
          </section>
        )}

        {/* Gates */}
        <section className="space-y-3">
          <h3 className="text-[13px] font-semibold text-foreground">Is there an edge?</h3>
          <div className="grid gap-3">
            <EdgeGate />
            <CrossAssetGate />
          </div>
        </section>

        {/* The machine's memory + what it has learned now lives on the Mind page (one consolidated surface). */}

        {/* Strategy Finder */}
        <section className="space-y-3">
          <h3 className="text-[13px] font-semibold text-foreground">Strategy Finder</h3>
          <FarmConsole />
        </section>

        {/* Activity */}
        {evtConnected && events.length > 0 && (
          <section className="space-y-3">
            <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
              <Activity className="size-4 text-iris-soft" /> Recent activity
            </h3>
            <Card>
              <CardContent className="pt-4">
                <ActivityTimeline events={events} />
              </CardContent>
            </Card>
          </section>
        )}

        {/* Graveyard */}
        {connected && population.killed > 0 && (
          <section className="space-y-3">
            <h3 className="text-[13px] font-semibold text-foreground">Graveyard</h3>
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
                <CardContent className="space-y-2">
                  {population.graveyard.map((row: GraveyardRow) => (
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
                </CardContent>
              </Card>
            </div>
          </section>
        )}
      </ExpandableSection>
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
          <span className="text-warn">
            kill rate {formatPct((funnel.killed / funnel.authored) * 100, 1)}
          </span>
        )}
        {funnel.gate_passed > 0 && funnel.authored > 0 && (
          <span className="text-quiet">
            gate pass rate {formatPct((funnel.gate_passed / funnel.authored) * 100, 1)}
          </span>
        )}
      </div>
    </div>
  );
}
