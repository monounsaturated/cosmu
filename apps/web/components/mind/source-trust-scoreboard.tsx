// Source-trust scoreboard — plain-English trust cards for every registered data source.
// Trust = freshness × realized gate contribution. Honest: sources with no data show
// status="no data", trust=0. Never fabricates. No LLM on this path.

import { AlertTriangle, CheckCircle, Clock, ShieldOff, XCircle } from "lucide-react";
import type { SourceTrustRow } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ---- status badge helpers --------------------------------------------------

type StatusKind = "fresh" | "recent" | "aging" | "stale" | "no data";

function statusBadgeVariant(status: StatusKind) {
  if (status === "fresh") return "up";
  if (status === "recent") return "iris";
  if (status === "aging") return "warn";
  return "outline";
}

function StatusIcon({ status }: { status: StatusKind }) {
  if (status === "fresh") return <CheckCircle className="size-3.5 text-up" />;
  if (status === "recent") return <Clock className="size-3.5 text-iris-soft" />;
  if (status === "aging") return <AlertTriangle className="size-3.5 text-warn" />;
  if (status === "stale") return <AlertTriangle className="size-3.5 text-down" />;
  return <XCircle className="size-3.5 text-quiet/50" />;
}

// ---- trust bar (visual only, no numbers fabricated) -----------------------

function TrustBar({ score }: { score: number }) {
  // 4 segments: 0-25%, 25-50%, 50-75%, 75-100%
  const filled = Math.round(score * 4);
  return (
    <div className="flex gap-0.5" aria-label={`Trust: ${Math.round(score * 100)}%`}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 w-3.5 rounded-sm",
            i < filled
              ? score >= 0.7
                ? "bg-up"
                : score >= 0.4
                  ? "bg-iris-soft"
                  : "bg-warn"
              : "bg-border/40"
          )}
        />
      ))}
    </div>
  );
}

// ---- single source row -----------------------------------------------------

function SourceRow({ row }: { row: SourceTrustRow }) {
  const status = (row.status ?? "no data") as StatusKind;
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border/40 bg-surface-2/20 px-2.5 py-2">
      <div className="flex items-center gap-2">
        <StatusIcon status={status} />
        <span className="font-mono text-[11.5px] font-medium text-foreground">{row.source}</span>
        {row.tier === "tier1" && (
          <span className="text-[9px] text-warn">LOW-CONF</span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <TrustBar score={row.trust_score} />
          <Badge variant={statusBadgeVariant(status)} className="text-[9px]">
            {row.freshness_label}
          </Badge>
        </div>
      </div>
      <p className="pl-5 text-[11px] leading-relaxed text-muted">{row.summary}</p>
      {row.features && row.features.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-5">
          {row.features.slice(0, 6).map((f) => (
            <span
              key={f}
              className="rounded border border-border/40 bg-background/40 px-1.5 py-0 font-mono text-[9.5px] text-quiet"
            >
              {f}
            </span>
          ))}
          {row.features.length > 6 && (
            <span className="text-[9.5px] text-quiet">+{row.features.length - 6} more</span>
          )}
        </div>
      )}
    </div>
  );
}

// ---- scoreboard ------------------------------------------------------------

export function SourceTrustScoreboard({
  rows,
  asOf,
}: {
  rows: SourceTrustRow[];
  asOf?: string | null;
}) {
  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
          <ShieldOff className="size-7 text-quiet/40" />
          <div className="space-y-1">
            <div className="text-[13px] font-medium">No sources registered yet</div>
            <p className="text-[12px] text-muted">
              Source trust scores appear once data has been ingested.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const freshCount = rows.filter((r) => r.status === "fresh" || r.status === "recent").length;
  const withGatePasses = rows.filter((r) => r.gate_pass_count > 0).length;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-[13px]">
          <span>Source scoreboard</span>
          <div className="flex gap-2">
            <Badge variant="muted" className="text-[10px]">
              {freshCount}/{rows.length} fresh
            </Badge>
            <Badge variant="muted" className="text-[10px]">
              {withGatePasses} contributed to gate
            </Badge>
          </div>
        </CardTitle>
        {asOf && (
          <p className="text-[10.5px] text-muted">
            Trust = freshness × gate contribution · as of {new Date(asOf).toLocaleTimeString()}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.map((row) => (
          <SourceRow key={row.source} row={row} />
        ))}
      </CardContent>
    </Card>
  );
}
