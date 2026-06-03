import { Activity } from "lucide-react";
import { getBrain, getEvents, getPopulation, engineConfigured } from "../data";
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
import { EmptyState, NotConnected, NotConnectedBanner } from "@/components/ui/honest-state";
import { formatPct } from "@/lib/utils";

export default async function LabPage() {
  const [
    { population, connected },
    { brain, connected: brainConnected },
    { events, connected: evtConnected }
  ] = await Promise.all([getPopulation(), getBrain(), getEvents()]);

  const anyConnected = connected || brainConnected;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="lab"
        title="What is the machine discovering?"
        aside={<Badge variant="muted">LLM proposes · Gate disposes</Badge>}
      />

      {!anyConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Versions tested" value={connected ? population.total : "—"} accent="iris" />
        <Stat label="In sim" value={connected ? population.forward_test : "—"} accent="up" />
        <Stat label="In graveyard" value={connected ? population.killed : "—"} accent="down" />
        <Stat label="Kill rate" value={connected && population.total ? formatPct(population.kill_rate * 100, 1) : "—"} accent="warn" />
      </div>

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
    </div>
  );
}
