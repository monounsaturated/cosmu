// Mind — the agent's credibility read-out: the followed-voices scoreboard (who the Mind listens to and how
// much to trust them), straight off GET /mind/credibility (realtime-data-lane P2). Lean + overview-led: a
// one-line panel summary, then the authority-sorted table. The Mind only REASONS — it never funds or fires;
// the deterministic Gate alone disposes (AGENTS.md "The Mind").
//
// HONESTY: not-connected → the engine-not-connected state; an empty panel → the honest "no voices registered"
// state (never a fabricated row). Every score is a real field the engine computed from resolved claims.

import { Suspense } from "react";
import { engineConfigured, getCredibility } from "../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected } from "@/components/ui/honest-state";
import { VoiceScoreboard } from "@/components/mind/voice-scoreboard";

export const dynamic = "force-dynamic";

export default function MindPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Mind" />
            <div className="skel" style={{ height: 360 }} />
          </>
        }
      >
        <MindData />
      </Suspense>
    </Page>
  );
}

async function MindData() {
  const { credibility, connected } = await getCredibility();

  if (!connected) {
    return (
      <>
        <Toolbar title="Mind" />
        <NotConnected
          configured={engineConfigured}
          what="The voice scoreboard is who the Mind follows and their measured authority — Brier-skill + citation-PageRank on resolved claims against the real tape. It appears here once the engine is connected — no demo rows."
        />
      </>
    );
  }

  return (
    <>
      <Toolbar title="Mind" />
      <VoiceScoreboard credibility={credibility} />
    </>
  );
}
