import { LineChart, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { ExpandableSection } from "@/components/ui/expandable-section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { SimSummary } from "@/components/paper/sim-summary";
import { TrackCard } from "@/components/paper/track-card";

// Paper is stage 3 in the lifecycle: strategies that have cleared the Gate run here on
// live data with no real money. Each track is held and marked-to-market across real bars. The
// per-track equity-since-funding is the hero; ≥ 30 paper days of net-of-fee proof is the
// recommended readiness signal before going Live. Every number is real or an honest zero/empty.
export default async function PaperPage() {
  const { leaderboard, connected } = await getLeaderboard();
  const allRows = leaderboard.rows as LeaderboardRow[];

  // Filter to paper-stage strategies (status = forward / forward_test / paper).
  const simRows = allRows.filter((r) => {
    const s = (r.status ?? "").toLowerCase();
    return s === "paper" || s === "forward_test" || s === "forward";
  });

  // Sort the hero list so the most decision-relevant tracks lead: live-ready first, then by paper age,
  // then by marked paper return. Pure presentation over real fields — no fabricated ordering signal.
  const ordered = [...simRows].sort((a, b) => {
    if (a.live_ready !== b.live_ready) return a.live_ready ? -1 : 1;
    if (b.paper_age_days !== a.paper_age_days) return b.paper_age_days - a.paper_age_days;
    return (b.paper_return_pct ?? 0) - (a.paper_return_pct ?? 0);
  });

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="paper"
        title="Papering on live data"
        aside={
          <Badge variant="info">
            <LineChart className="size-3" /> no real money
          </Badge>
        }
      />

      <StrategyStages />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Strategies currently in paper appear here once the engine is connected. Each track runs on real bars with no real capital — the clock starts from Gate approval."
        />
      ) : simRows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="No strategies in Paper yet."
              hint={
                <>
                  Strategies move here automatically once they clear the Gate in{" "}
                  <Link href="/strategies" className="text-iris-soft hover:underline">
                    Backtest
                  </Link>
                  . The Gate decides — you don&apos;t move them manually.
                </>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <SimSummary rows={simRows} />

          {/* Hero: per-track live equity since funding, paper age toward live-ready, divergence integrated. */}
          <div className="grid gap-3 md:grid-cols-2">
            {ordered.map((row) => (
              <TrackCard key={row.version_id} row={row} />
            ))}
          </div>

          {/* Progressive disclosure: the full sortable/filterable table for a denser read. */}
          <ExpandableSection
            showLabel="Show full table"
            hideLabel="Hide full table"
            summary={null}
          >
            <Card>
              <CardContent className="pt-5">
                <StrategiesTable rows={simRows} context="paper" />
              </CardContent>
            </Card>
          </ExpandableSection>

          <SimNote />
        </>
      )}
    </div>
  );
}

// Calm footer note on how to READ this surface honestly — demoted below the data, never above it. The
// machine's deterministic Gate disposes; this restates the one trap the operator flagged (don't read the
// backtest column as paper performance) and where the readiness signal points.
function SimNote() {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-start gap-2.5">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-up" />
          <div className="space-y-1.5">
            <p className="text-[12.5px] font-medium text-foreground">How to read this</p>
            <p className="text-[12px] leading-relaxed text-muted">
              Every track here cleared the deterministic Gate and now runs on real market bars with a
              standalone $100k Paper track — no pooled wallet.{" "}
              <span className="font-medium text-foreground">Forward since funding</span> is the REAL
              net-of-fee return since the Gate funded the track — a just-armed track reads{" "}
              <span className="tabular text-quiet">day 0 · +0.00%</span> until it accrues history.{" "}
              <span className="font-medium text-foreground">Backtest OOS</span> is historical and proves
              nothing forward — don&apos;t read it as paper performance.
            </p>
            <p className="text-[12px] leading-relaxed text-muted">
              The recommended readiness signal is{" "}
              <span className="font-medium text-foreground">≥ 30 paper days of net-of-fee profit</span>,
              but you decide when to{" "}
              <Link href="/live" className="text-iris-soft hover:underline">
                go Live
              </Link>
              . The Gate&apos;s 5 interlocks are the hard requirement. The divergence badge is a glance,
              not a gate — it never moves money.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
