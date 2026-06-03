// What the agent KNOWS — every data source it can read, grouped by the perspective that reads it, each tagged
// with whether it is ingested + fresh and its latest point-in-time value. Honest: a source with no data shows
// as "not ingested yet", never as live.

import { Database } from "lucide-react";
import type { MindLens } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function MindKnows({ knows }: { knows: MindLens[] }) {
  if (knows.length === 0) {
    return <p className="text-[12.5px] text-quiet">No data sources registered.</p>;
  }
  return (
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
              <div
                key={item.name}
                className="flex items-center justify-between gap-3 rounded-md border border-border/40 bg-surface-2/20 px-2.5 py-1.5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-mono text-[11.5px] text-foreground">{item.name}</span>
                    {item.low_confidence ? <span className="text-[10px] text-warn">low-conf</span> : null}
                  </div>
                  <div className="truncate text-[10.5px] text-quiet">{item.source}</div>
                </div>
                <div className="shrink-0 text-right">
                  {item.ingested ? (
                    <>
                      <div className="tabular text-[12px] font-semibold text-up">
                        {item.value !== null && item.value !== undefined ? item.value : "live"}
                      </div>
                      <div className="text-[10px] text-quiet">fresh</div>
                    </>
                  ) : (
                    <div className="text-[10.5px] text-quiet">not ingested yet</div>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
