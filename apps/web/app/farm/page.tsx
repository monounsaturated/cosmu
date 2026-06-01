import { Dna, Skull } from "lucide-react";
import { getPopulation, fallbackCohort } from "../data";
import type { GraveyardRow } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { FarmConsole } from "./farm-console";
import { EdgeGate } from "@/components/research/edge-gate";
import { formatPct } from "@/lib/utils";

export default async function FarmPage() {
  const population = await getPopulation();

  return (
    <div className="mx-auto max-w-[1400px] space-y-8 px-5 py-7 lg:px-7">
      <div className="relative overflow-hidden rounded-xl border border-border/70 card-grad p-6 lg:p-7">
        <div className="ring-grid pointer-events-none absolute inset-0 opacity-[0.3] [mask-image:radial-gradient(600px_240px_at_90%_0%,black,transparent)]" />
        <div className="relative">
          <Badge variant="iris">
            <Dna className="size-3" /> evolution loop · 24/7
          </Badge>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            The farm tests <span className="text-iris-soft">tons of strategies at once</span>
          </h1>
          <p className="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-muted">
            Seeds, single-operator mutations, high-variance wildcards and imported Pine scripts all flow through one
            deterministic funnel. The scorer kills 95%+ and records every death — the rigor gates capital, never ideas.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Population tested" value={population.total} accent="iris" />
        <Stat label="On paper sleeves" value={population.paper} accent="up" />
        <Stat label="In graveyard" value={population.killed} accent="down" />
        <Stat label="Kill rate" value={formatPct(population.kill_rate * 100, 1)} accent="warn" />
      </div>

      <section className="space-y-4">
        <SectionHeader eyebrow="research" title="Is there an edge?" aside={<Badge variant="muted">stop-or-go · pre-registered bar</Badge>} />
        <EdgeGate />
      </section>

      <section className="space-y-4">
        <SectionHeader eyebrow="lab" title="Autonomous farming" />
        <FarmConsole fallback={fallbackCohort} />
      </section>

      <section className="space-y-4">
        <SectionHeader
          eyebrow="population"
          title="Cumulative graveyard"
          aside={<Badge variant="muted">learn from deaths · never survivor-bias</Badge>}
        />
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
              <Badge variant="down"><Skull className="size-3" /> with kill reasons</Badge>
            </CardHeader>
            <CardContent className="space-y-2">
              {population.graveyard.map((row: GraveyardRow) => (
                <div key={row.version_id} className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-[12.5px] font-medium text-foreground">{row.name}</div>
                    <div className="text-[11px] text-quiet">{row.origin}</div>
                  </div>
                  <div className="flex flex-wrap justify-end gap-1">
                    {row.kill_reason.split(",").map((r) => (
                      <Badge key={r} variant="down">{r.replace(/_/g, " ")}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
