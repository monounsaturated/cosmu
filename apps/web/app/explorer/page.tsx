import { Telescope } from "lucide-react";
import { engineConfigured, getExplorerList } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { NotConnected } from "@/components/ui/honest-state";
import { ExplorerClient } from "./explorer-client";

// Strategy Explorer — lets the operator pick a strategy + venue + asset and see
// how it works: equity curve (gross vs net), entry/exit markers, and a glanceable
// stats panel with every honest gate metric. Overlay mode: same strategy, two assets.
//
// Data: read from stored engine results only — never triggers a new backtest.
// Empty-state: honest "not available" for every field that has no stored data.

export default async function ExplorerPage() {
  const { list, connected } = await getExplorerList();

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="explorer"
        title="Strategy Explorer"
        aside={
          <Badge variant="iris">
            <Telescope className="size-3" /> pick · compare · understand
          </Badge>
        }
      />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="The Strategy Explorer shows stored backtest results — equity curves (gross vs net), entry/exit markers, and gate stats. Nothing is fabricated. Connect the engine to explore."
        />
      ) : (
        <ExplorerClient initialList={list} />
      )}
    </div>
  );
}
