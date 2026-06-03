"use client";

// module: ActivityTimeline — a readable "what the machine did" feed from GET /events (Deliverable #2).
// Each event is actor · kind · ref · time. Events are grouped into a few plain-language families
// (research, gate, sim, live, system) so the operator can watch the autonomous loop work without
// decoding raw kind strings. Pure presentation over the real ledger — never fabricated; an unknown
// kind falls back to the "system" family rather than being hidden. Reduced-motion respected (no
// entry animation; the only motion is a CSS pulse the OS setting already silences via globals.css).

import type { Event } from "@cosmu/contracts-ts";
import { Activity, Microscope, Radio, ShieldCheck, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";
import { cn } from "@/lib/utils";

type Family = {
  label: string;
  icon: LucideIcon;
  // OKLch token class for the icon + dot.
  tone: string;
};

const FAMILIES: Record<string, Family> = {
  research: { label: "research", icon: Microscope, tone: "text-iris-soft" },
  gate: { label: "gate", icon: ShieldCheck, tone: "text-info" },
  sim: { label: "sim", icon: Wallet, tone: "text-up" },
  live: { label: "live", icon: Radio, tone: "text-warn" },
  system: { label: "system", icon: Activity, tone: "text-quiet" }
};

// Map a raw event kind to a family. Substring rules keep this stable as the engine adds kinds; an
// unrecognized kind lands in "system" (shown, never dropped).
function familyForKind(kind: string): keyof typeof FAMILIES {
  const k = kind.toLowerCase();
  if (k.includes("live") || k.includes("order") || k.includes("execution") || k.includes("armed")) {
    return "live";
  }
  if (k.includes("gate") || k.includes("holdout") || k.includes("screen") || k.includes("survivor")) return "gate";
  if (k.includes("track") || k.includes("sim") || k.includes("fund") || k.includes("forward") || k.includes("paper") || k.includes("wallet")) return "sim";
  if (
    k.includes("research") ||
    k.includes("cohort") ||
    k.includes("run") ||
    k.includes("finder") ||
    k.includes("inbox") ||
    k.includes("draft") ||
    k.includes("author")
  ) {
    return "research";
  }
  return "system";
}

// Human time: relative for recent events, falling back to a short absolute stamp. Point-in-time —
// uses only the event's own ts.
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return `${Math.max(secs, 0)}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function actorLabel(actor: string): string {
  if (actor === "master") return "the machine";
  if (actor === "human") return "you";
  return actor.replace(/_/g, " ");
}

export function ActivityTimeline({ events, limit = 40 }: { events: Event[]; limit?: number }) {
  if (!events || events.length === 0) {
    return (
      <EmptyState
        title="No activity yet."
        hint="Every step of the autonomous loop — research passes, gate decisions, track funding and defunding — is recorded here as it happens. Nothing is fabricated."
      />
    );
  }

  // Newest first, capped so the feed stays readable.
  const ordered = [...events].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()).slice(0, limit);

  return (
    <ol className="relative space-y-0">
      {ordered.map((event, i) => {
        const fam = FAMILIES[familyForKind(event.kind)];
        const Icon = fam.icon;
        const isLast = i === ordered.length - 1;
        const ref = event.ref_id ? `${event.ref_type ?? "ref"}:${event.ref_id}` : event.ref_type ?? null;
        return (
          <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
            {/* Spine + node */}
            <div className="relative flex flex-col items-center">
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border border-border/70 bg-surface-2/60",
                  fam.tone
                )}
              >
                <Icon className="size-3.5" />
              </span>
              {!isLast ? <span className="mt-1 w-px flex-1 bg-border/60" /> : null}
            </div>

            {/* Body */}
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[12.5px] font-medium text-foreground">{event.kind.replace(/_/g, " ")}</span>
                <Badge variant="muted">{fam.label}</Badge>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-quiet">
                <span>{actorLabel(event.actor)}</span>
                {ref ? (
                  <>
                    <span className="text-border-strong">·</span>
                    <span className="font-mono">{ref}</span>
                  </>
                ) : null}
                <span className="text-border-strong">·</span>
                <time dateTime={event.ts} title={new Date(event.ts).toLocaleString()}>
                  {relativeTime(event.ts)}
                </time>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
