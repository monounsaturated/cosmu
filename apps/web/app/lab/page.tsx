import { getBrain, getPopulation, engineConfigured } from "../data";
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
import { Tooltip } from "@/components/ui/tooltip";
import { EmptyState, NotConnected, NotConnectedBanner } from "@/components/ui/honest-state";
import { formatPct } from "@/lib/utils";

// Lab answers ONE question: what is the machine discovering?
// Research brain (authored -> gated -> survivors -> graveyard), the Strategy Finder runs + config
// library, gate funnel + survival distribution, and the data sources.
export default async function LabPage() {
  const [{ population, connected }, { brain, connected: brainConnected }] = await Promise.all([
    getPopulation(),
    getBrain()
  ]);

  const anyConnected = connected || brainConnected;

  return (
    <div className="mx-auto max-w-[1400px] space-y-8 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="lab"
        title="What is the machine discovering?"
        aside={<Badge variant="muted">LLM proposes · the deterministic Gate disposes</Badge>}
      />

      {!anyConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Versions tested" value={connected ? population.total : "—"} accent="iris" />
        <Stat label="On paper Sleeves" value={connected ? population.paper : "—"} accent="up" />
        <Stat label="In graveyard" value={connected ? population.killed : "—"} accent="down" />
        <Stat label="Kill rate" value={connected && population.total ? formatPct(population.kill_rate * 100, 1) : "—"} accent="warn" />
      </div>

      {/* Research brain: LLM state, gate funnel, survivors, ranking, sources, graveyard */}
      <section className="space-y-3">
        <SectionHeader
          eyebrow="brain"
          title="Authored → gated → survivors → graveyard"
          aside={<Badge variant="muted">deterministic Gate decides · model only orders</Badge>}
        />

        {!brainConnected ? (
          <NotConnected
            configured={engineConfigured}
            what="The research brain shows the LLM state, the deterministic gate funnel, survivors, the validation-queue ranking, data sources, and the graveyard — all from the live engine."
          />
        ) : (
          <>
            <div className="grid gap-3 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-1.5">
                    Gate funnel
                    <Tooltip content="Every generated Version runs the deterministic Gate. Most are killed — the funnel shows how many survive and the kill rate." />
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
                    <Tooltip content="Each survivor's survival score — the model's estimate the edge persists out-of-sample. It only orders the validation queue; it never vetoes." />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <SurvivalDistribution survivors={brain.survivors} />
                </CardContent>
              </Card>
            </div>

            <ResearchBrain brain={brain} />
          </>
        )}
      </section>

      {/* Gates: is there an edge, and does cross-asset add to it? */}
      <section className="space-y-3">
        <SectionHeader eyebrow="gates" title="Is there an edge?" />
        <div className="grid gap-3">
          <EdgeGate />
          <CrossAssetGate />
        </div>
      </section>

      {/* Strategy Finder: autonomous cohort runs + Pine config library */}
      <section className="space-y-4">
        <SectionHeader
          eyebrow="strategy finder"
          title="Test a wide population, keep the survivors"
          aside={<Badge variant="muted">seeds · mutations · wildcards · Pine</Badge>}
        />
        <FarmConsole />
      </section>

      {/* Cumulative graveyard — learn from deaths */}
      <section className="space-y-4">
        <SectionHeader
          eyebrow="population"
          title="Cumulative graveyard"
          aside={<Badge variant="muted">learn from deaths · never survivor-bias</Badge>}
        />
        {!connected ? (
          <NotConnected configured={engineConfigured} what="The cumulative graveyard shows every Version that has died, by origin lane and kill reason." />
        ) : population.killed === 0 ? (
          <Card>
            <CardContent>
              <EmptyState title="Nothing has died yet." hint="As the Strategy Finder tests batches, killed Versions accumulate here with their kill reasons." />
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 lg:grid-cols-[1fr_1.6fr]">
            <Card>
              <CardHeader>
                <CardTitle>By origin lane</CardTitle>
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
        )}
      </section>
    </div>
  );
}
