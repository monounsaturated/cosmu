// module: control-room panels for the Overview — the two human-facing halves of "does the machine need
// me?". Side by side:
//   • NeedsYou       — the queue of decisions only a human may make (the machine proposes, you dispose).
//                      Reuses the canonical NeedsYouInbox so the Overview and the Console never disagree
//                      about what is waiting; approving never itself moves money.
//   • RecentActivity — the last few steps of the autonomous loop (research → gate → fund → live), reusing
//                      the ActivityTimeline over the real /events ledger, with a link to the full Console.
//
// HONESTY CONTRACT: both panels render only real engine data. Offline → honest "status unknown"; connected
// but empty → an honest "nothing needs you" / "no activity yet". Nothing is fabricated.

import Link from "next/link";
import { ArrowRight, Inbox, History } from "lucide-react";
import type { Event, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { NeedsYouInbox } from "@/components/autonomy/needs-you-inbox";
import { ActivityTimeline } from "@/components/observability/activity-timeline";

export function NeedsYouCard({
  recommendations,
  connected,
  configured
}: {
  recommendations: Recommendation[];
  connected: boolean;
  configured: boolean;
}) {
  const open = recommendations.filter((r) => r.state === "open").length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Inbox className="size-4 text-iris-soft" /> Needs you
        </CardTitle>
        {open > 0 ? (
          <Badge variant="warn">
            {open} waiting
          </Badge>
        ) : (
          <span className="text-[12px] text-quiet">human-only decisions</span>
        )}
      </CardHeader>
      <CardContent>
        <NeedsYouInbox initial={recommendations} connected={connected} configured={configured} />
      </CardContent>
    </Card>
  );
}

export function RecentActivityCard({ events, connected }: { events: Event[]; connected: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <History className="size-4 text-iris-soft" /> Recent activity
        </CardTitle>
        <span className="text-[12px] text-quiet">what the machine has been doing</span>
      </CardHeader>
      <CardContent>
        {!connected ? (
          <p className="py-6 text-center text-[12.5px] text-quiet">
            Machine status unknown — activity appears once the engine is connected.
          </p>
        ) : (
          <>
            <ActivityTimeline events={events} limit={6} />
            {events.length > 6 ? (
              <Link
                href="/console"
                className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-surface-2/20 px-4 py-2 text-[12.5px] font-medium text-muted transition-colors hover:border-border hover:bg-surface-2/50 hover:text-foreground"
              >
                View the full loop <ArrowRight className="size-3.5" />
              </Link>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
