// module: the Overview "What to do next" card — the control room's single answer to "given everything the
// system found, what should the operator actually do?". It derives 1–3 concrete, prioritised suggestions
// PURELY from real engine state already on the page (open recommendations, forward-proven survivors, the
// population funnel, data freshness, autonomy run-state, net return). It never fabricates a suggestion: with
// nothing pressing it says so honestly. Each suggestion is advisory — the deterministic Gate still disposes;
// nothing here moves money.

import Link from "next/link";
import { ArrowRight, CheckCircle2, Compass } from "lucide-react";
import type { DataSource } from "@/app/data";
import type { LeaderboardRow, PopulationResponse, Recommendation } from "@cosmu/contracts-ts";
import type { AutonomyStatus } from "@/app/autonomy-contracts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Tone = "do" | "good" | "info";

type Suggestion = { tone: Tone; text: string; href?: string; cta?: string };

const dot: Record<Tone, string> = {
  do: "bg-iris",
  good: "bg-up",
  info: "bg-info"
};

function truncate(s: string, n = 90): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

// Build the prioritised list from REAL state. Highest-leverage / most time-sensitive first; we render the top 3.
function buildSuggestions({
  population,
  leaderboard,
  recommendations,
  autonomy,
  dataFreshness,
  hasTrackRecord,
  returnPct
}: WhatNextProps): Suggestion[] {
  const out: Suggestion[] = [];
  const open = recommendations.filter((r) => r.state === "open");
  const liveReady = leaderboard.filter((r) => r.status !== "killed" && r.live_ready);
  const proving = population.forward_test;
  const freshSources = dataFreshness.filter((s) => s.points > 0).length;
  const totalSources = dataFreshness.length;
  const alive = Math.max(0, population.total - population.killed);

  if (autonomy.paused) {
    out.push({
      tone: "do",
      text: "The autonomous machine is paused — resume it (Autonomy card below) so it keeps authoring and gating new strategies."
    });
  }

  if (open.length > 0) {
    const top = open[0];
    out.push({
      tone: "do",
      text: `${open.length} recommendation${open.length > 1 ? "s" : ""} need your decision${top ? `: "${truncate(top.body)}"` : ""}.`,
      href: "/steer",
      cta: "Review"
    });
  }

  if (liveReady.length > 0) {
    const s = liveReady[0];
    out.push({
      tone: "good",
      text: `"${s.name}" is forward-proven and net-positive — review it for a live allocation.`,
      href: `/strategy/${s.version_id}`,
      cta: "Inspect"
    });
  }

  if (population.total === 0) {
    out.push({
      tone: "do",
      text: "No strategies yet. Drop a strategy vibe in the Idea inbox below, or let the next autonomous tick author one.",
      href: "/lab",
      cta: "Open Lab"
    });
  }

  if (totalSources > 0 && freshSources === 0) {
    out.push({
      tone: "info",
      text: `Data is still backfilling — none of ${totalSources} source${totalSources > 1 ? "s have" : " has"} reported points yet. Signals that need fresh data will wait.`,
      href: "/mind",
      cta: "See Mind"
    });
  }

  if (alive > 0 && proving > 0 && liveReady.length === 0) {
    out.push({
      tone: "info",
      text: `${proving} strateg${proving > 1 ? "ies are" : "y is"} in Simulation — none has enough net-positive forward evidence for live yet. Give them time.`,
      href: "/forward-test",
      cta: "Simulation"
    });
  }

  if (hasTrackRecord && returnPct >= 0) {
    out.push({
      tone: "good",
      text: "Net positive across Simulation tracks. Keep monitoring; consider a small live allocation once a track is proven.",
      href: "/forward-test",
      cta: "Simulation"
    });
  }

  if (out.length === 0) {
    out.push({
      tone: "info",
      text: "Nothing is waiting on you. The machine is running autonomously — drop new ideas anytime; the Gate decides what survives.",
      href: "/lab",
      cta: "Open Lab"
    });
  }

  return out.slice(0, 3);
}

interface WhatNextProps {
  population: PopulationResponse;
  leaderboard: LeaderboardRow[];
  recommendations: Recommendation[];
  autonomy: AutonomyStatus;
  dataFreshness: DataSource[];
  hasTrackRecord: boolean;
  returnPct: number;
}

export function WhatNext(props: WhatNextProps) {
  const suggestions = buildSuggestions(props);
  const allClear = suggestions.length === 1 && suggestions[0].tone === "info" && props.recommendations.every((r) => r.state !== "open");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {allClear ? <CheckCircle2 className="size-4 text-up" /> : <Compass className="size-4 text-iris-soft" />}
          What to do next
        </CardTitle>
        <span className="text-[11px] text-quiet">From real state</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {suggestions.map((s, i) => {
          const inner = (
            <div className="flex items-start gap-3">
              <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${dot[s.tone]}`} />
              <p className="text-[13px] leading-relaxed text-muted">{s.text}</p>
              {s.href ? (
                <span className="ml-auto inline-flex shrink-0 items-center gap-1 self-center text-[12px] font-medium text-iris-soft">
                  {s.cta ?? "Open"} <ArrowRight className="size-3.5" />
                </span>
              ) : null}
            </div>
          );
          const cls = "block rounded-md border border-border/50 bg-surface-2/30 px-3 py-2.5";
          return s.href ? (
            <Link key={i} href={s.href} className={`${cls} group transition-colors hover:border-border hover:bg-surface-2/55`}>
              {inner}
            </Link>
          ) : (
            <div key={i} className={cls}>
              {inner}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
