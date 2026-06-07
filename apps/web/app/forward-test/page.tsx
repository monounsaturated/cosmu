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
import { DivergenceBadge } from "@/components/forward-test/divergence-badge";

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
        <>
          <DivergenceWatch rows={simRows} />
          <Card>
            <CardContent className="pt-5">
              <StrategiesTable rows={simRows} context="simulation" />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

// Calm, per-track SIM-vs-backtest divergence strip: an early warning that a forward test has stopped tracking the
// backtest it was funded on (alpha-decay / regime-shift). Reads the leaderboard contract's divergence_status (from
// master/divergence.py) — never a fabricated number. A track with too few marked days shows the honest "not enough
// data" state. MONITORING ONLY: nothing here gates or moves money; it's a glance for the operator.
function DivergenceWatch({ rows }: { rows: LeaderboardRow[] }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="mb-3 flex items-start gap-2.5">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-up" />
          <div className="space-y-1">
            <p className="text-[12.5px] font-medium text-foreground">Divergence watch</p>
            <p className="text-[12px] leading-relaxed text-muted">
              Early warning when a track&apos;s real forward return stops tracking the backtest it was funded on —
              the gap is forward minus the backtest pro-rated to the same elapsed window. A glance, not a gate.
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {rows.map((row) => (
            <div
              key={row.version_id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-2/40 px-3 py-2"
            >
              <span className="truncate text-[12.5px] font-medium text-foreground">{row.name}</span>
              <DivergenceBadge row={row} />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
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
