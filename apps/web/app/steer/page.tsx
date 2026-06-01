import { MessageSquare, Radio } from "lucide-react";
import { SteerBox } from "./steer-box";
import { engineConfigured, getEvents, getRecommendations } from "../data";
import type { Event, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnectedBanner } from "@/components/ui/honest-state";

// Steer answers ONE question: how do I nudge the machine?
// NL steer commands + recommendations + ML-through-NL asks. Authoring lives in Claude Code / the
// Overview inbox — Steer stays slim and ops-focused.
export default async function SteerPage() {
  const [{ items: recommendations, connected: recConnected }, { events, connected: evtConnected }] = await Promise.all([
    getRecommendations(),
    getEvents()
  ]);

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
            <CardTitle>Recommendations</CardTitle>
            <Badge variant="warn">needs you</Badge>
          </CardHeader>
          <CardContent className="space-y-3">
            {recommendations.length === 0 ? (
              <EmptyState
                title={recConnected ? "Nothing waiting on you right now." : "Connect the engine to see recommendations."}
                hint={recConnected ? "The engine raises a recommendation when a decision needs your call." : undefined}
              />
            ) : (
              recommendations.map((rec: Recommendation) => (
                <div key={rec.id} className="rounded-md border border-border/60 bg-surface-2/40 p-3">
                  <Badge variant="warn">{rec.kind.replace(/_/g, " ")}</Badge>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{rec.body}</p>
                </div>
              ))
            )}
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
