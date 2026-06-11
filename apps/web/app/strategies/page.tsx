import type { ReactNode } from "react";
import { ChartCandlestick, Inbox, Microscope, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { PopulationStrip } from "@/components/strategies/population-strip";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";

// Strategies (the Leaderboard, docs/PRODUCT.md Epic B) answers ONE question: which strategies deserve my
// attention/capital, on what edge? Every Version runs on its own standalone $100k track, ranked by
// risk-adjusted % (deflated OOS Sharpe). The page leads with the population SHAPE (counts by stage),
// then the faceted, sortable table slices the cohort by HOW it makes money: signal-family (primary,
// derived from referenced features) + asset class · venue · timeframe · status · origin · edge-type.
// Rows link to per-Version detail. No pooled wallet, no demo rows.
export default async function StrategiesPage() {
  const { leaderboard, connected } = await getLeaderboard();
  const rows = leaderboard.rows as LeaderboardRow[];

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="backtest · strategies"
        title="Every Version, ranked & faceted"
        aside={
          <Badge variant="iris">
            <ChartCandlestick className="size-3" /> ranked by risk-adjusted %
          </Badge>
        }
      />

      <StrategyStages />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Every Version is judged in net-of-fee % on its own track — no pooled wallet. The faceted, ranked table appears here once the engine is connected — no demo rows."
        />
      ) : rows.length === 0 ? (
        <>
          <BornNote />
          <Card>
            <CardContent>
              <EmptyState
                title="No Versions yet — the Lab hasn't produced any."
                hint="Once the Lab authors a batch (or you drop an idea in the inbox) and Versions reach Paper, they show up here grouped by stage."
              />
            </CardContent>
          </Card>
        </>
      ) : (
        <>
          {/* Lead with the answer: the population shape at a glance, before the dense ranked table. */}
          <PopulationStrip rows={rows} />
          <Card>
            <CardContent className="pt-5">
              <StrategiesTable rows={rows} />
            </CardContent>
          </Card>
          <BornNote />
        </>
      )}
    </div>
  );
}

// Two authoring paths, one Gate — the model in one read, kept calm and secondary (it sits under the
// table once a cohort exists, and above the empty state when one doesn't). No decorative icon banner.
function BornNote() {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
          <NoteItem icon={<Microscope className="size-3.5" />} title="The machine authors them">
            autonomously in the{" "}
            <Link href="/lab" className="text-iris-soft hover:underline">
              Lab
            </Link>{" "}
            — seeds, mutations and wildcards, around the clock.
          </NoteItem>
          <NoteItem icon={<Inbox className="size-3.5" />} title="You drop ideas">
            a thesis or Pine script, into the inbox via Claude Code.
          </NoteItem>
          <p className="flex items-center gap-1.5 text-[11.5px] text-quiet sm:justify-end">
            <ShieldCheck className="size-3.5 shrink-0 text-up" />
            <span>
              Both flow through the <span className="font-medium text-foreground">same Gate</span>.
            </span>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function NoteItem({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-[12px] leading-relaxed text-muted">
      <span className="mt-0.5 shrink-0 text-quiet">{icon}</span>
      <span>
        <span className="font-medium text-foreground">{title}</span> {children}
      </span>
    </div>
  );
}
