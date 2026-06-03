import { ArrowRight, ChartCandlestick, Inbox, Microscope, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard, getPopulation } from "../data";
import type { LeaderboardRow, PopulationResponse } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";

// Strategies answers ONE question: where is every Version in its lifecycle, and which are winning?
// The searchable, stage-segmented table is the old leaderboard's real home; rows link to per-Version
// detail. A short "how a strategy is born" note + the Lab → Strategies → Forward-test → Live funnel make the
// pipeline obvious at a glance.
export default async function StrategiesPage() {
  const [{ leaderboard, connected }, { population }] = await Promise.all([getLeaderboard(), getPopulation()]);
  const rows = leaderboard.rows as LeaderboardRow[];

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="strategies"
        title="Every Version, by lifecycle stage"
        aside={
          <Badge variant="iris">
            <ChartCandlestick className="size-3" /> ranked by Score (deflated Sharpe)
          </Badge>
        }
      />

      {/* The funnel — where Strategies sits in the pipeline, with live counts at each stage. */}
      <FunnelStrip population={connected ? population : null} />

      {/* How a strategy is born — plain language, both authoring paths through the one Gate. */}
      <BornNote />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Every Version is judged in net-of-fee % on its own track — no pooled wallet. The searchable, stage-by-stage table appears here once the engine is connected — no demo rows."
        />
      ) : rows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="No Versions yet — the Lab hasn't produced any."
              hint="Once the Lab authors a batch (or you drop an idea in the inbox) and Versions reach Forward-test, they show up here grouped by stage."
            />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="pt-5">
            <StrategiesTable rows={rows} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// The pipeline as a DATA funnel, not a button row: each stage carries its live count so the strip earns its
// place (it shows how many Versions survive each step), marks "you are here", and is intentionally NOT
// clickable — the top nav already navigates. A null population (engine offline) renders dashes, never fakes.
function FunnelStrip({ population }: { population: PopulationResponse | null }) {
  const total = population?.total ?? 0;
  const fwdPlusLive = population?.forward_test ?? 0;
  const live = population?.live ?? 0;
  const killed = population?.killed ?? 0;
  const screenedAlive = Math.max(0, total - fwdPlusLive - killed); // past the screen, alive, pre-forward-test
  const forwardTest = Math.max(0, fwdPlusLive - live);

  const count = (n: number) => (population ? String(n) : "—");
  const steps: { label: string; tag: string; value: string; here?: boolean }[] = [
    { label: "Lab", tag: "discover", value: population ? "live" : "—" },
    { label: "Strategies", tag: "screened", value: count(screenedAlive), here: true },
    { label: "Forward-test", tag: "proving", value: count(forwardTest) },
    { label: "Live", tag: "real money", value: count(live) }
  ];
  const killPct = population && total ? Math.round(population.kill_rate * 100) : null;

  return (
    <section aria-label="Pipeline">
      <ol className="flex flex-wrap items-stretch gap-1.5">
        {steps.map((step, i) => (
          <li key={step.label} className="flex items-center gap-1.5">
            <div
              aria-current={step.here ? "step" : undefined}
              className={
                "flex min-w-[88px] flex-col rounded-lg border px-3 py-1.5 " +
                (step.here ? "border-iris/50 bg-iris/10" : "border-border/60 bg-surface-2/30")
              }
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className={"text-[12.5px] font-semibold " + (step.here ? "text-foreground" : "text-muted")}>
                  {step.label}
                </span>
                <span className={"tabular text-[13px] font-semibold " + (step.here ? "text-iris-soft" : "text-foreground")}>
                  {step.value}
                </span>
              </span>
              <span className="text-[10px] uppercase tracking-wide text-quiet">{step.tag}</span>
            </div>
            {i < steps.length - 1 ? <ArrowRight className="size-3.5 shrink-0 text-quiet" aria-hidden /> : null}
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[11px] text-quiet">
        {population
          ? `${total} Versions authored · ${killed} in the graveyard${killPct !== null ? ` · ${killPct}% kill rate` : ""}`
          : "Counts appear once the engine is connected."}
      </p>
    </section>
  );
}

// Two authoring paths, one Gate. Kept short and plain so a new operator gets the model in one read.
function BornNote() {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-start gap-2.5">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-iris-soft" />
          <div className="space-y-2.5">
            <p className="text-[12.5px] font-medium text-foreground">How a strategy is born</p>
            <div className="grid gap-2.5 sm:grid-cols-2">
              <div className="flex items-start gap-2 text-[12px] leading-relaxed text-muted">
                <Microscope className="mt-0.5 size-3.5 shrink-0 text-quiet" />
                <span>
                  <span className="font-medium text-foreground">The machine authors them</span> autonomously in the{" "}
                  <Link href="/lab" className="text-iris-soft hover:underline">
                    Lab
                  </Link>{" "}
                  — seeds, mutations and wildcards, around the clock.
                </span>
              </div>
              <div className="flex items-start gap-2 text-[12px] leading-relaxed text-muted">
                <Inbox className="mt-0.5 size-3.5 shrink-0 text-quiet" />
                <span>
                  <span className="font-medium text-foreground">You drop ideas</span> — a thesis or Pine script — into the
                  inbox via Claude Code.
                </span>
              </div>
            </div>
            <p className="flex items-center gap-1.5 text-[11.5px] text-quiet">
              <ShieldCheck className="size-3.5 shrink-0 text-up" />
              Both flow through the <span className="font-medium text-foreground">same deterministic Gate</span> — no
              shortcut to Forward-test or Live.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
