import { BrainCircuit, Radio } from "lucide-react";
import { ConsoleBox } from "./console-box";
import { getEvents, getRecommendations } from "../data";
import type { Event, Recommendation } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";

export default async function ConsolePage() {
  const [recommendations, events] = await Promise.all([getRecommendations(), getEvents()]);

  return (
    <div className="mx-auto max-w-[1100px] space-y-8 px-5 py-7 lg:px-7">
      <SectionHeader
        eyebrow="console"
        title="Author a strategy in plain language"
        aside={
          <Badge variant="iris">
            <BrainCircuit className="size-3" /> you propose · the scorer disposes
          </Badge>
        }
      />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>New strategy brief</CardTitle>
            <CardDescription>Describe an idea in words; the engine returns a typed, validated draft you can farm.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <ConsoleBox />
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
              <p className="text-[12.5px] text-quiet">Nothing waiting on you right now.</p>
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
            {events.map((event: Event) => (
              <div key={event.id} className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[12.5px] font-medium text-foreground">{event.kind.replace(/_/g, " ")}</div>
                  <div className="text-[11px] text-quiet">
                    {event.actor} · {event.ref_type ?? "system"}
                  </div>
                </div>
                <span className="size-1.5 rounded-full bg-info/80" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
