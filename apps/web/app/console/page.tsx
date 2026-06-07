// Console — the control surface (docs/PRODUCT.md Epic D; VISION §1.4, §11 "the Console is the star").
// It does the only things a human MUST do: ARM (the global live toggle, off by default, presented as a
// deliberate two-step action showing the 5 interlocks), DECIDE (the recommendation/approval inbox — the
// machine proposes, you dispose), and STEER (plain-language nudges + ML asks, money-adjacent ones need
// approval). A reporting + steering surface — the deterministic gate/scorer alone disposes, and arming
// live is an explicit two-click confirm. Honest offline states everywhere; nothing is fabricated.

import { MessageSquare, ShieldCheck, Terminal } from "lucide-react";
import { engineConfigured, getAutonomyStatus, getOverview, getRecommendations } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { GlobalLiveToggle } from "@/components/live/global-live-toggle";
import { NeedsYouInbox } from "@/components/autonomy/needs-you-inbox";
import { AutonomyPanel } from "@/components/autonomy/autonomy-panel";
import { SteerBox } from "../steer/steer-box";

export default async function ConsolePage() {
  const [{ overview, connected }, { items: recommendations, connected: recConnected }, { status: autonomy, connected: autonomyConnected }] =
    await Promise.all([getOverview(), getRecommendations(), getAutonomyStatus()]);

  return (
    <div className="mx-auto max-w-[1000px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="console"
        title="Arm · decide · steer"
        aside={
          <Badge variant="muted">
            <ShieldCheck className="size-3" /> You move money — nothing else does
          </Badge>
        }
      />

      {/* ARM — the highest-gravity control in the product. A deliberate two-step action that surfaces the
          5 interlocks. Off by default; this is the focal point of the page. */}
      <GlobalLiveToggle initialEnabled={Boolean(overview.live_enabled)} connected={connected} />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* DECIDE — the recommendation/approval inbox. The machine proposes; you dispose. */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-1.5">
                <Terminal className="size-4 text-iris-soft" /> Needs you
              </CardTitle>
              <CardDescription>Approvals only a human may make. Approving never itself moves money.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <NeedsYouInbox initial={recommendations} connected={recConnected} configured={engineConfigured} />
          </CardContent>
        </Card>

        {/* STEER — plain-language ops + ML asks. */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-1.5">
                <MessageSquare className="size-4 text-iris-soft" /> Steer in plain language
              </CardTitle>
              <CardDescription>Research nudges or re-rank asks. The Gate still decides what survives.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <SteerBox />
          </CardContent>
        </Card>
      </div>

      {/* What the autonomous loop is doing — pause/resume/run-a-cycle. */}
      <AutonomyPanel initial={autonomy} connected={autonomyConnected} configured={engineConfigured} />
    </div>
  );
}
