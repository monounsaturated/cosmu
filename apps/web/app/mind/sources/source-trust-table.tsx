"use client";

// Sortable + filterable source trust table.

import { AlertTriangle, CheckCircle, Clock, ShieldOff, XCircle } from "lucide-react";
import type { SourceTrustRow } from "@cosmu/contracts-ts";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";
import { cn } from "@/lib/utils";

type StatusKind = "fresh" | "recent" | "aging" | "stale" | "no data";

function statusVariant(status: StatusKind) {
  if (status === "fresh") return "up" as const;
  if (status === "recent") return "iris" as const;
  if (status === "aging") return "warn" as const;
  return "outline" as const;
}

function StatusIcon({ status }: { status: StatusKind }) {
  if (status === "fresh") return <CheckCircle className="size-3.5 text-up" />;
  if (status === "recent") return <Clock className="size-3.5 text-iris-soft" />;
  if (status === "aging") return <AlertTriangle className="size-3.5 text-warn" />;
  if (status === "stale") return <AlertTriangle className="size-3.5 text-down" />;
  return <XCircle className="size-3.5 text-quiet/50" />;
}

function TrustBar({ score }: { score: number }) {
  const filled = Math.round(score * 4);
  return (
    <div className="flex gap-0.5" aria-label={`Trust: ${Math.round(score * 100)}%`}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 w-3.5 rounded-sm",
            i < filled
              ? score >= 0.7 ? "bg-up" : score >= 0.4 ? "bg-iris-soft" : "bg-warn"
              : "bg-border/40"
          )}
        />
      ))}
    </div>
  );
}

const COLUMNS: ColumnDef<SourceTrustRow>[] = [
  {
    key: "source",
    label: "Source",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => {
      const status = (r.status ?? "no data") as StatusKind;
      return (
        <div className="flex items-center gap-2">
          <StatusIcon status={status} />
          <span className="font-mono text-[12px] font-medium text-foreground">{r.source}</span>
          {r.tier === "tier1" && (
            <span className="text-[9px] text-warn">LOW-CONF</span>
          )}
        </div>
      );
    }
  },
  {
    key: "status",
    label: "Status",
    sortable: true,
    renderCell: (r) => {
      const status = (r.status ?? "no data") as StatusKind;
      return (
        <Badge variant={statusVariant(status)} className="text-[10px]">
          {r.freshness_label || status}
        </Badge>
      );
    }
  },
  {
    key: "trust_score",
    label: "Trust",
    sortable: true,
    align: "right",
    renderCell: (r) => (
      <div className="flex items-center justify-end gap-2">
        <TrustBar score={r.trust_score} />
        <span className="tabular text-[12px] text-foreground">
          {Math.round(r.trust_score * 100)}%
        </span>
      </div>
    )
  },
  {
    key: "gate_pass_count",
    label: "Gate passes",
    sortable: true,
    align: "right",
    renderCell: (r) => (
      <span className="tabular text-[12px] text-muted">{r.gate_pass_count}</span>
    )
  },
  {
    key: "hours_since",
    label: "Last seen",
    sortable: true,
    renderCell: (r) => {
      if (r.hours_since === null || r.hours_since === undefined) {
        return <span className="text-[12px] text-quiet">—</span>;
      }
      const h = r.hours_since;
      const label = h < 1 ? "<1h ago" : h < 24 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`;
      return <span className="tabular text-[12px] text-muted">{label}</span>;
    }
  },
  {
    key: "summary",
    label: "Summary",
    hideOnCard: false,
    renderCell: (r) => (
      <div className="space-y-1">
        <p className="text-[12px] leading-relaxed text-muted">{r.summary}</p>
        {r.features && r.features.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {r.features.slice(0, 5).map((f) => (
              <span
                key={f}
                className="rounded border border-border/40 bg-background/40 px-1.5 font-mono text-[9.5px] text-quiet"
              >
                {f}
              </span>
            ))}
            {r.features.length > 5 && (
              <span className="text-[9.5px] text-quiet">+{r.features.length - 5} more</span>
            )}
          </div>
        )}
      </div>
    )
  }
];

export function SourceTrustTable({ rows }: { rows: SourceTrustRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No sources registered yet"
        hint="Source trust scores appear once data has been ingested."
        icon={<ShieldOff className="size-5" />}
      />
    );
  }

  return (
    <DataTablePage
      columns={COLUMNS}
      rows={rows}
      keyOf={(r) => r.source}
      initialSort="trust_score"
      initialDir="desc"
      searchPlaceholder="Search source, summary…"
      matchSearch={(r, q) =>
        r.source.toLowerCase().includes(q) ||
        r.summary.toLowerCase().includes(q) ||
        (r.status ?? "").toLowerCase().includes(q)
      }
      emptyLabel="No sources match the search."
    />
  );
}
