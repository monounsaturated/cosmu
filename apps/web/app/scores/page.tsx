// Scores — a compact cockpit of per-source + composite INDEX scores grouped by category (crypto · social ·
// macro · OSINT · metals/forex), each with freshness and a plain-language "what this means" review. Source
// pickers grey out when a source's key isn't set on the engine. Honest: a category/source with no data
// renders offline (connected=false), never a fabricated number. Read-only — no money path here.

import { Gauge } from "lucide-react";
import { getScores, engineConfigured } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import { ScoresCockpit } from "@/components/scores/scores-cockpit";

export default async function ScoresPage() {
  const { scores, connected } = await getScores();

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="scores"
        title="Per-source &amp; composite index scores"
        aside={
          <Badge variant="muted">
            <Gauge className="size-3" /> Freshness × gate contribution
          </Badge>
        }
      />

      {!connected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      <ScoresCockpit scores={scores} />
    </div>
  );
}
