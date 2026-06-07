// module: the Overview "Data freshness" panel — the honest answer to "is the system actually fed?". One row
// per registered data source with its point count and how long ago it last reported. A source with zero
// points reads "no data yet" (backfilling), never a fabricated freshness. With the engine unreachable it
// says so plainly. Read-only; this only reports what has been ingested — it never moves money.
//
// Rendered bare (no Card chrome) so it composes cleanly inside the Overview's tabbed "detail" section,
// matching the other panels there. A small inline head gives it a title + a link out to the Mind.

import Link from "next/link";
import { ArrowRight, Database } from "lucide-react";
import type { DataSource } from "@/app/data";
import { EmptyState } from "@/components/ui/honest-state";
import { timeAgo } from "@/lib/utils";

export function DataFreshness({ sources, connected }: { sources: DataSource[]; connected: boolean }) {
  const fresh = sources.filter((s) => s.points > 0).length;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-foreground">
            <span className="text-iris-soft">
              <Database className="size-4" />
            </span>
            Data freshness
          </div>
          <p className="mt-1 text-[12px] text-quiet">Is the machine actually fed? Per-source coverage.</p>
        </div>
        <Link
          href="/mind"
          className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-iris-soft transition-colors hover:underline"
        >
          Mind <ArrowRight className="size-3.5" />
        </Link>
      </div>

      {!connected || sources.length === 0 ? (
        <EmptyState
          title={connected ? "No data sources reporting yet." : "Engine not connected."}
          hint={
            connected
              ? "Sources backfill on a schedule. Counts and timestamps appear here as real points land — nothing is fabricated."
              : "Set API_BASE_URL to see which feeds are reporting."
          }
          icon={<Database className="size-5" />}
        />
      ) : (
        <>
          <div className="mb-2 text-[11.5px] text-quiet">
            <span className="text-up">{fresh}</span> of {sources.length} source{sources.length > 1 ? "s" : ""} reporting
          </div>
          <ul className="space-y-1.5">
            {sources.slice(0, 8).map((s) => {
              const has = s.points > 0;
              return (
                <li
                  key={s.source}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={`size-1.5 shrink-0 rounded-full ${has ? "bg-up" : "bg-border-strong"}`} />
                    <span className="truncate text-[12.5px] text-foreground">{s.source}</span>
                  </span>
                  <span className="shrink-0 text-[11.5px] text-quiet">
                    {has ? (
                      <>
                        <span className="tabular text-muted">{s.points.toLocaleString()}</span> pts ·{" "}
                        {timeAgo(s.last_at) ?? "—"}
                      </>
                    ) : (
                      "no data yet"
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
