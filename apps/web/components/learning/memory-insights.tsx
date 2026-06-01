// module: MemoryInsights — surfaces GET /memory/insights (Deliverable #3): the durable lessons the
// brain carries forward. Two kinds: dead-ends it now avoids, and winner patterns it leans into.
// Split into two columns so the operator sees both sides of the flywheel at a glance. Server
// component; honest empty state when nothing has been learned yet.

import { Ban, Sparkles } from "lucide-react";
import type { MemoryInsight } from "@/app/data";
import { EmptyState } from "@/components/ui/honest-state";

export function MemoryInsights({ insights }: { insights: MemoryInsight[] }) {
  if (!insights || insights.length === 0) {
    return (
      <EmptyState
        title="No lessons recorded yet."
        hint="As Versions die or persist, the brain distills what to avoid (dead-ends) and what to repeat (winner patterns) here."
      />
    );
  }

  const deadEnds = insights.filter((i) => i.kind === "dead_end");
  const winners = insights.filter((i) => i.kind === "winner_pattern");

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <InsightColumn
        title="Dead-ends avoided"
        icon={<Ban className="size-4 text-down" />}
        tone="border-down/30"
        items={deadEnds}
        emptyLabel="No dead-ends recorded yet."
      />
      <InsightColumn
        title="Winner patterns"
        icon={<Sparkles className="size-4 text-up" />}
        tone="border-up/30"
        items={winners}
        emptyLabel="No winner patterns recorded yet."
      />
    </div>
  );
}

function InsightColumn({
  title,
  icon,
  tone,
  items,
  emptyLabel
}: {
  title: string;
  icon: React.ReactNode;
  tone: string;
  items: MemoryInsight[];
  emptyLabel: string;
}) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-foreground">
        {icon}
        {title}
        <span className="tabular text-quiet">· {items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="rounded-md border border-border/50 bg-surface-2/20 px-3 py-2.5 text-[11.5px] text-quiet">{emptyLabel}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((insight, i) => (
            <li key={`${insight.ref}-${i}`} className={`rounded-md border bg-surface-2/30 px-3 py-2.5 ${tone}`}>
              <p className="text-[12.5px] leading-relaxed text-muted">{insight.text}</p>
              {insight.ref ? <div className="mt-1 font-mono text-[10.5px] text-quiet">{insight.ref}</div> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
