import { ArrowRight, ChartCandlestick, Inbox, Microscope, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";

// Strategies answers ONE question: where is every Version in its lifecycle, and which are winning?
// The searchable, stage-segmented table is the old leaderboard's real home; rows link to per-Version
// detail. A short "how a strategy is born" note + the Lab → Strategies → Paper → Live funnel make the
// pipeline obvious at a glance.
export default async function StrategiesPage() {
  const { leaderboard, connected } = await getLeaderboard();
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

      {/* The funnel — where Strategies sits in the pipeline. */}
      <FunnelStrip />

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
              hint="Once the Lab authors a batch (or you drop an idea in the inbox) and Versions earn Sleeves, they show up here grouped by stage."
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

// Lab → Strategies → Paper → Live, with Strategies highlighted as "you are here".
function FunnelStrip() {
  const steps: { href: string; label: string; here?: boolean }[] = [
    { href: "/lab", label: "Lab" },
    { href: "/strategies", label: "Strategies", here: true },
    { href: "/forward-test", label: "Forward-test" },
    { href: "/live", label: "Live" }
  ];
  return (
    <nav aria-label="Pipeline" className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
      {steps.map((step, i) => (
        <div key={step.href} className="flex items-center gap-1.5">
          <Link
            href={step.href}
            aria-current={step.here ? "step" : undefined}
            className={
              step.here
                ? "rounded-full border border-iris/50 bg-iris/10 px-3 py-1 font-medium text-foreground"
                : "rounded-full border border-border/70 bg-surface-2/30 px-3 py-1 text-muted transition-colors hover:border-border hover:text-foreground"
            }
          >
            {step.label}
          </Link>
          {i < steps.length - 1 ? <ArrowRight className="size-3.5 text-quiet" /> : null}
        </div>
      ))}
    </nav>
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
              shortcut to Paper or Live.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
