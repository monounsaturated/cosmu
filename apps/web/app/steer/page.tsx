import { MessageSquare, Radio } from "lucide-react";
import { SteerBox } from "./steer-box";
import { engineConfigured, getAutonomyStatus, getEvents, getRecommendations } from "../data";
import type { Event } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnectedBanner } from "@/components/ui/honest-state";
import { AutonomyPanel } from "@/components/autonomy/autonomy-panel";
import { NeedsYouInbox } from "@/components/autonomy/needs-you-inbox";

// Steer answers ONE question: how do I nudge the machine?
// NL steer commands + recommendations + ML-through-NL asks. Authoring lives in Claude Code / the
// Overview inbox — Steer stays slim and ops-focused.
export default async function SteerPage() {
  const [
    { items: recommendations, connected: recConnected },
    { events, connected: evtConnected },
    { status: autonomy, connected: autonomyConnected }
  ] = await Promise.all([getRecommendations(), getEvents(), getAutonomyStatus()]);

  return (
    <div className="mx-auto max-w-[1100px] space-y-8 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="steer"
        title="Nudge the machine in plain language"
        aside={
          <Badge variant="iris">
            <MessageSquare className="size-3" /> you steer · the Gate disposes
          </Badge>
        }
      />

      {!recConnected && !evtConnected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* The autonomy control: pause / resume / run-a-cycle for the machine the human oversees. */}
      <AutonomyPanel initial={autonomy} connected={autonomyConnected} configured={engineConfigured} />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Steer &amp; ask</CardTitle>
            <CardDescription>Send a research-routing nudge, or ask the survival model to re-rank / retrain — both in words.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <SteerBox />
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Needs you</CardTitle>
            <Badge variant="warn">approve · dismiss</Badge>
          </CardHeader>
          <CardContent>
            <NeedsYouInbox initial={recommendations} connected={recConnected} configured={engineConfigured} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Audit stream</CardTitle>
            <Radio className="size-4 text-info" />
          </CardHeader>
          <CardContent className="space-y-2.5">
            {events.length === 0 ? (
              <EmptyState
                title={evtConnected ? "No activity yet." : "Connect the engine to see the audit stream."}
                hint={evtConnected ? "Every action the machine takes is recorded here." : undefined}
              />
            ) : (
              events.map((event: Event) => (
                <div key={event.id} className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[12.5px] font-medium text-foreground">{event.kind.replace(/_/g, " ")}</div>
                    <div className="text-[11px] text-quiet">
                      {event.actor} · {event.ref_type ?? "system"}
                    </div>
                  </div>
                  <span className="size-1.5 rounded-full bg-info/80" />
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
