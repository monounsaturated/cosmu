// What the agent KNOWS — every data source it can read, grouped by the perspective that reads it, each tagged
// with whether it is ingested + fresh and its latest point-in-time value. Honest: a source with no data shows
// as "not ingested yet", never as live. Shows freshness (time since last ingest) and live vs stale status.

import { Activity, AlertTriangle, CheckCircle, Clock, Database, XCircle } from "lucide-react";
import type { MindLens, MindSourceItem } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function formatValue(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  if (Math.abs(v) < 0.01 && v !== 0) return v.toExponential(2);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  return v.toFixed(Math.abs(v) < 1 ? 4 : 2);
}

function freshness(lastAt: string | null | undefined): { label: string; stale: boolean } {
  if (!lastAt) return { label: "never", stale: true };
  const diff = Date.now() - new Date(lastAt).getTime();
  const hours = diff / 3.6e6;
  if (hours < 1) return { label: `${Math.round(diff / 60000)}m ago`, stale: false };
  if (hours < 24) return { label: `${Math.round(hours)}h ago`, stale: false };
  const days = Math.round(hours / 24);
  return { label: `${days}d ago`, stale: days > 1 };
}

function SourceRow({ item }: { item: MindSourceItem }) {
  const { label: freshLabel, stale } = item.ingested ? freshness(item.last_at) : { label: "—", stale: false };

  return (
    <div className="flex items-center gap-3 rounded-md border border-border/40 bg-surface-2/20 px-2.5 py-2">
      <div className="shrink-0">
        {item.ingested ? (
          stale ? (
            <AlertTriangle className="size-3.5 text-warn" />
          ) : (
            <CheckCircle className="size-3.5 text-up" />
          )
        ) : (
          <XCircle className="size-3.5 text-quiet/50" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate font-mono text-[11.5px] text-foreground">{item.name}</span>
          {item.low_confidence ? <span className="text-[9px] text-warn">LOW-CONF</span> : null}
          <Badge variant={item.tier === "tier0" ? "muted" : "outline"} className="ml-auto text-[9px]">
            {item.tier}
          </Badge>
        </div>
        <div className="truncate text-[10.5px] text-quiet">{item.source}</div>
      </div>
      <div className="shrink-0 text-right">
        {item.ingested ? (
          <>
            <div className="tabular text-[12px] font-semibold text-foreground">
              {formatValue(item.value)}
            </div>
            <div className={cn("flex items-center justify-end gap-1 text-[10px]", stale ? "text-warn" : "text-quiet")}>
              <Clock className="size-2.5" />
              {freshLabel}
            </div>
          </>
        ) : (
          <div className="text-[10.5px] italic text-quiet/60">not ingested</div>
        )}
      </div>
    </div>
  );
}

export function MindKnows({ knows }: { knows: MindLens[] }) {
  if (knows.length === 0) {
    return <p className="text-[12.5px] text-quiet">No data sources registered.</p>;
  }

  const totalIngested = knows.reduce((a, l) => a + l.ingested, 0);
  const totalSources = knows.reduce((a, l) => a + l.total, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-lg border border-border/50 bg-surface-2/20 px-4 py-2.5">
        <Activity className="size-4 text-iris-soft" />
        <div className="flex-1">
          <span className="text-[13px] font-semibold text-foreground">{totalIngested}</span>
          <span className="text-[12px] text-quiet"> of {totalSources} feeds live</span>
        </div>
        <div className="flex gap-4 text-[11px] text-quiet">
          <span className="flex items-center gap-1">
            <CheckCircle className="size-3 text-up" /> Live
          </span>
          <span className="flex items-center gap-1">
            <AlertTriangle className="size-3 text-warn" /> Stale (&gt;24h)
          </span>
          <span className="flex items-center gap-1">
            <XCircle className="size-3 text-quiet/50" /> Not ingested
          </span>
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {knows.map((lens) => (
          <Card key={lens.perspective}>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <Database className="size-3.5 text-iris-soft" /> {lens.perspective}
              </CardTitle>
              <Badge variant={lens.ingested > 0 ? "up" : "muted"}>
                {lens.ingested}/{lens.total} ingested
              </Badge>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {lens.items.map((item) => (
                <SourceRow key={item.name} item={item} />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
