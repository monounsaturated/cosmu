import { ChartCandlestick } from "lucide-react";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";

// Strategies answers ONE question: browse/inspect any Strategy/Version.
// The searchable table is the old leaderboard's real home; rows link to per-Version detail.
export default async function StrategiesPage() {
  const { leaderboard, connected } = await getLeaderboard();
  const rows = leaderboard.rows as LeaderboardRow[];

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="strategies"
        title="Browse every Strategy and Version"
        aside={
          <Badge variant="iris">
            <ChartCandlestick className="size-3" /> ranked by Score (deflated Sharpe)
          </Badge>
        }
      />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Every Version earns a standardized $100k Sleeve, judged in net-of-fee %. The searchable table appears here once the engine is connected — no demo rows."
        />
      ) : rows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="No Versions yet — the Lab hasn't produced any."
              hint="Once the Strategy Finder tests a batch and Versions earn Sleeves, they show up here to browse and inspect."
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
