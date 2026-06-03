// News/intel panel — recent typed, dated, point-in-time scored news events.
// Each event has a sign (bullish/bearish/neutral), magnitude (0-1), and timestamp.
// Honest empty state when no news has been ingested. No LLM on this display path.

import { Newspaper, TrendingDown, TrendingUp, Minus } from "lucide-react";
import type { NewsEventRow } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function EventIcon({ eventType }: { eventType: string }) {
  if (eventType === "bullish") return <TrendingUp className="size-3.5 text-up shrink-0" />;
  if (eventType === "bearish") return <TrendingDown className="size-3.5 text-down shrink-0" />;
  return <Minus className="size-3.5 text-quiet/60 shrink-0" />;
}

function eventBadgeVariant(eventType: string) {
  if (eventType === "bullish") return "up";
  if (eventType === "bearish") return "down";
  return "muted";
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  const hours = diff / 3.6e6;
  if (hours < 1) return `${Math.round(diff / 60000)}m ago`;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function MagnitudeBar({ value }: { value: number }) {
  // value in [-1, 1]; render magnitude (abs) as a bar with direction colour
  const magnitude = Math.min(1, Math.abs(value));
  const isPositive = value > 0.05;
  const isNegative = value < -0.05;
  return (
    <div className="flex h-1.5 w-10 overflow-hidden rounded-full bg-border/30">
      <div
        className={cn(
          "h-full rounded-full",
          isPositive ? "bg-up" : isNegative ? "bg-down" : "bg-quiet/40"
        )}
        style={{ width: `${magnitude * 100}%` }}
      />
    </div>
  );
}

function EventRow({ event }: { event: NewsEventRow }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-border/40 bg-surface-2/20 px-2.5 py-2">
      <EventIcon eventType={event.event_type} />
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2">
          <Badge variant={eventBadgeVariant(event.event_type)} className="text-[9px]">
            {event.event_type}
          </Badge>
          <MagnitudeBar value={event.value} />
          <span className="ml-auto font-mono text-[10px] text-quiet">{event.value > 0 ? "+" : ""}{event.value.toFixed(2)}</span>
          <span className="text-[10px] text-muted">{formatTs(event.ts)}</span>
        </div>
      </div>
    </div>
  );
}

export function NewsIntelPanel({
  events,
  symbol,
}: {
  events: NewsEventRow[];
  symbol: string;
}) {
  const bullish = events.filter((e) => e.event_type === "bullish").length;
  const bearish = events.filter((e) => e.event_type === "bearish").length;
  const neutral = events.filter((e) => e.event_type === "neutral").length;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-[13px]">
          <span className="flex items-center gap-1.5">
            <Newspaper className="size-4 text-iris-soft" />
            News / intel
            <span className="font-mono text-[11px] text-muted">{symbol}</span>
          </span>
          {events.length > 0 && (
            <div className="flex gap-1.5">
              <Badge variant="up" className="text-[9px]">{bullish} bullish</Badge>
              <Badge variant="down" className="text-[9px]">{bearish} bearish</Badge>
              <Badge variant="muted" className="text-[9px]">{neutral} neutral</Badge>
            </div>
          )}
        </CardTitle>
        <p className="text-[10.5px] text-muted">
          Typed, dated, point-in-time scored events · value = sign × magnitude in [−1, +1]
        </p>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <Newspaper className="size-7 text-quiet/30" />
            <div className="text-[12.5px] text-muted">
              No scored events yet. Run the ingest pass to populate.
            </div>
          </div>
        ) : (
          <div className="space-y-1.5">
            {events.map((event, i) => (
              <EventRow key={`${event.ts ?? i}-${i}`} event={event} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
