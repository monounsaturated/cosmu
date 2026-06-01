"use client";

// module: the brain panel's graveyard list, with progressive disclosure. Summary first (a few
// recent deaths), the rest revealed on demand so the panel stays scannable. Each death shows the
// kill reasons as badges — learn from deaths, never survivor-bias. Honest empty state when nothing
// has died yet. Client-only because the show-more toggle holds state.

import { useState } from "react";
import { Badge } from "@/components/ui/badge";

const PREVIEW = 3;

export function Graveyard({ rows }: { rows: { name: string; reasons: string[] }[] }) {
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) {
    return <p className="text-[12.5px] text-muted">Nothing has died yet — the graveyard is empty.</p>;
  }

  const shown = expanded ? rows : rows.slice(0, PREVIEW);
  const hidden = rows.length - shown.length;

  return (
    <div className="space-y-1.5">
      {shown.map((row) => (
        <div
          key={row.name}
          className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
        >
          <span className="min-w-0 truncate text-[12.5px] text-foreground">{row.name}</span>
          <span className="flex flex-wrap justify-end gap-1">
            {row.reasons.length === 0 ? (
              <Badge variant="muted">no reason recorded</Badge>
            ) : (
              row.reasons.map((r) => (
                <Badge key={r} variant="down">
                  {r.replace(/_/g, " ")}
                </Badge>
              ))
            )}
          </span>
        </div>
      ))}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full rounded-md border border-border/50 bg-surface-2/20 px-3 py-1.5 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          Show {hidden} more death{hidden === 1 ? "" : "s"}
        </button>
      ) : expanded && rows.length > PREVIEW ? (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="w-full rounded-md border border-border/50 bg-surface-2/20 px-3 py-1.5 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          Show less
        </button>
      ) : null}
    </div>
  );
}
