// module: the Overview "Right now" band — the command center's at-a-glance answer to "what is
// happening right now?". Synthesises four engine vitals + the last few events into one dense card:
//   · Engine   — connected / offline, with the last autonomous tick time.
//   · Strategies — alive count, with how many are proving in sim and how many are in the graveyard.
//   · Mind     — the analyst panel's debated consensus + conviction (reasoning only; never funds).
//   · Needs you — open recommendations, surfacing the top one.
// HONEST: every cell renders from real engine data; with nothing yet it says so plainly (no fabricated
// status, no fake tick time). Detail lives one click away on each linked surface.

import Link from "next/link";
import { Activity, ArrowRight, Brain, ListChecks, MessageSquare } from "lucide-react";
import type { MindResponse, PopulationResponse, Recommendation, Event } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AutonomyStatus } from "@/app/autonomy-contracts";
import { formatEventKind, timeAgo } from "@/lib/utils";

const consensusMeta: Record<MindResponse["consensus"], { label: string; cls: string }> = {
  bullish: { label: "Bullish", cls: "text-up" },
  bearish: { label: "Bearish", cls: "text-down" },
  neutral: { label: "Neutral", cls: "text-muted" }
};

// One vital cell: a labelled headline with a one-line sub, optionally linking to its detail surface.
function Vital({
  icon,
  label,
  href,
  children
}: {
  icon: React.ReactNode;
  label: string;
  href?: string;
  children: React.ReactNode;
}) {
  const head = (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">
        <span className="text-quiet">{icon}</span>
        {label}
      </span>
      {href ? <ArrowRight className="size-3 text-quiet transition-colors group-hover:text-iris-soft" /> : null}
    </div>
  );
  const body = <div className="mt-2">{children}</div>;
  if (href) {
    return (
      <Link href={href} className="group block p-4 transition-colors hover:bg-surface-2/40">
        {head}
        {body}
      </Link>
    );
  }
  return (
    <div className="p-4">
      {head}
      {body}
    </div>
  );
}

export function RightNow({
  connected,
  autonomy,
  population,
  mind,
  recommendations,
  events
}: {
  connected: boolean;
  autonomy: AutonomyStatus;
  population: PopulationResponse;
  mind: MindResponse;
  recommendations: Recommendation[];
  events: Event[];
}) {
  const lastTick = timeAgo(autonomy.last_tick_at);
  const alive = Math.max(0, population.total - population.killed);
  const con = consensusMeta[mind.consensus] ?? consensusMeta.neutral;
  const convictionPct = Math.round((mind.conviction ?? 0) * 100);
  const open = recommendations.filter((r) => r.state === "open");
  const topRec = open[0];
  const recent = events.slice(0, 3);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Activity className="size-4 text-iris-soft" /> Right now
        </CardTitle>
        <Badge variant={connected ? "up" : "muted"}>
          {connected ? (lastTick ? `Engine live · tick ${lastTick}` : "Engine live") : "Engine offline"}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {/* Four vitals, divider-separated, collapsing to two columns then one. */}
        <div className="grid grid-cols-1 divide-y divide-border/60 border-y border-border/60 sm:grid-cols-2 sm:divide-x lg:grid-cols-4 lg:divide-y-0">
          <Vital icon={<Activity className="size-3.5" />} label="Engine">
            <div className={`text-lg font-semibold tracking-tight ${connected ? "text-foreground" : "text-quiet"}`}>
              {connected ? (autonomy.paused ? "Paused" : "Running") : "Offline"}
            </div>
            <div className="mt-0.5 truncate text-[11.5px] text-quiet">
              {connected
                ? autonomy.cycles_run > 0
                  ? `${autonomy.cycles_run} cycles · ${autonomy.next_action || "idle"}`
                  : "no cycles yet"
                : "set API_BASE_URL to connect"}
            </div>
          </Vital>

          <Vital icon={<ListChecks className="size-3.5" />} label="Strategies" href="/strategies">
            <div className="text-lg font-semibold tracking-tight tabular text-foreground">{alive}</div>
            <div className="mt-0.5 truncate text-[11.5px] text-quiet">
              <span className="text-up">{population.forward_test} simulation</span> ·{" "}
              <span className="text-info">{population.live} live</span> ·{" "}
              <span className="text-down">{population.killed} graveyard</span>
            </div>
          </Vital>

          <Vital icon={<Brain className="size-3.5" />} label="Mind" href="/mind">
            <div className={`text-lg font-semibold tracking-tight ${con.cls}`}>
              {con.label}
              {mind.contested ? <span className="ml-1 align-middle text-[10px] font-medium uppercase text-warn">contested</span> : null}
            </div>
            <div className="mt-0.5 truncate text-[11.5px] text-quiet">
              {mind.stances.length ? `${convictionPct}% conviction · ${mind.stances.length} analysts` : "no signal yet — abstaining"}
            </div>
          </Vital>

          <Vital icon={<MessageSquare className="size-3.5" />} label="Needs you" href="/steer">
            <div className="text-lg font-semibold tracking-tight tabular text-foreground">
              {open.length}
              <span className="ml-1 text-[11.5px] font-normal text-quiet">open</span>
            </div>
            <div className="mt-0.5 truncate text-[11.5px] text-quiet">{topRec ? topRec.body : "nothing waiting on you"}</div>
          </Vital>
        </div>

        {/* Last 3 events — a thin activity ribbon under the vitals. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-[11.5px]">
          <span className="font-semibold uppercase tracking-[0.1em] text-quiet">Latest</span>
          {recent.length ? (
            recent.map((e) => (
              <span key={e.id} className="inline-flex items-center gap-1.5 text-muted">
                <span className="size-1.5 rounded-full bg-info/80" />
                {formatEventKind(e.kind)}
                <span className="text-quiet">{timeAgo(e.ts) ?? ""}</span>
              </span>
            ))
          ) : (
            <span className="text-quiet">No activity yet — the machine logs every action here as it runs.</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
