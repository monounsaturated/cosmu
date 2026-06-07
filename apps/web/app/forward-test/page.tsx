import { LineChart, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { StrategiesTable } from "@/components/research/strategies-table";

// Simulation is stage 3 in the lifecycle: strategies that have cleared the Gate run here on
// live data with no real money. Each track is held and marked-to-market across real bars.
// ≥ 30 forward days of net-of-fee proof is the recommended signal before going Live.
export default async function ForwardTestPage() {
  const { leaderboard, connected } = await getLeaderboard();
  const allRows = leaderboard.rows as LeaderboardRow[];

  // Filter to simulation-stage strategies (status = forward / forward_test / paper).
  const simRows = allRows.filter((r) => {
    const s = (r.status ?? "").toLowerCase();
    return s === "forward_test" || s === "forward" || s === "paper";
  });

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="simulation"
        title="Forward-testing on live data"
        aside={
          <Badge variant="up">
            <LineChart className="size-3" /> no real money
          </Badge>
        }
      />

      <StrategyStages />

      <SimNote />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Strategies currently in simulation appear here once the engine is connected. Each track runs on real bars with no real capital — the clock starts from Gate approval."
        />
      ) : simRows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="No strategies in Simulation yet."
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
        <Card>
          <CardContent className="pt-5">
            <StrategiesTable rows={simRows} context="simulation" />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SimNote() {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-start gap-2.5">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-up" />
          <div className="space-y-1.5">
            <p className="text-[12.5px] font-medium text-foreground">Live data · no capital</p>
            <p className="text-[12px] leading-relaxed text-muted">
              Every strategy here cleared the deterministic Gate. It now runs on real market bars with a
              standalone $100k paper track — no pooled wallet. The recommended readiness signal is{" "}
              <span className="font-medium text-foreground">≥ 30 forward days of net-of-fee profit</span>, but you
              decide when to{" "}
              <Link href="/live" className="text-iris-soft hover:underline">
                go Live
              </Link>
              . The Gate&apos;s 5 interlocks are the hard requirement.
            </p>
            <p className="text-[12px] leading-relaxed text-muted">
              Read the table honestly: <span className="font-medium text-foreground">Forward</span> is the REAL
              net-of-fee return marked to market since the Gate funded this track — a just-armed track reads{" "}
              <span className="tabular text-quiet">day 0 · +0.00%</span> until it accrues forward history, and a
              flat or losing track shows its true (0 or negative) number.{" "}
              <span className="font-medium text-foreground">Backtest OOS</span> is historical and proves nothing
              forward. Don&apos;t read the backtest column as forward performance.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
