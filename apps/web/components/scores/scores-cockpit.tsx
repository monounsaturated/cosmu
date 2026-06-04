// Scores cockpit — per-source + composite INDEX scores grouped by category (crypto · social · macro ·
// OSINT · metals/forex). Each category shows its index, freshness, and a plain-language "what this means"
// review; each source is a picker row that is GREYED/disabled when its key isn't set on the engine.
// HONEST: a category/source with no data renders offline (connected=false) — never a fabricated score.

import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Gauge,
  Lock,
  Plug,
  XCircle
} from "lucide-react";
import type { ScoreCategory, ScoreSourceRow, ScoresResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type StatusKind = "fresh" | "recent" | "aging" | "stale" | "no data" | "offline";

function statusBadgeVariant(status: string) {
  if (status === "fresh") return "up" as const;
  if (status === "recent") return "iris" as const;
  if (status === "aging") return "warn" as const;
  if (status === "stale") return "down" as const;
  return "outline" as const;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "fresh") return <CheckCircle className="size-3.5 text-up" />;
  if (status === "recent") return <Clock className="size-3.5 text-iris-soft" />;
  if (status === "aging") return <AlertTriangle className="size-3.5 text-warn" />;
  if (status === "stale") return <AlertTriangle className="size-3.5 text-down" />;
  return <XCircle className="size-3.5 text-quiet/50" />;
}

// ── index dial: a compact 0–100 read with a grade colour. null = honest offline. ──
function gradeColor(score: number | null | undefined) {
  if (score == null) return "text-quiet";
  if (score >= 0.7) return "text-up";
  if (score >= 0.4) return "text-iris-soft";
  if (score > 0) return "text-warn";
  return "text-quiet";
}

function IndexValue({ score, className }: { score: number | null | undefined; className?: string }) {
  if (score == null) {
    return <span className={cn("tabular text-quiet", className)}>—</span>;
  }
  return <span className={cn("tabular font-semibold", gradeColor(score), className)}>{Math.round(score * 100)}</span>;
}

function TrustBar({ score }: { score: number }) {
  const filled = Math.round(score * 4);
  return (
    <div className="flex gap-0.5" aria-label={`Score: ${Math.round(score * 100)}%`}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 w-3 rounded-sm",
            i < filled ? (score >= 0.7 ? "bg-up" : score >= 0.4 ? "bg-iris-soft" : "bg-warn") : "bg-border/40"
          )}
        />
      ))}
    </div>
  );
}

// ── one source: a picker row, disabled (greyed) when its key isn't on the engine ──
function SourceRow({ row }: { row: ScoreSourceRow }) {
  const disabled = row.disabled;
  return (
    <div
      role="button"
      aria-disabled={disabled || !row.connected}
      title={disabled ? `${row.key_name} not set on the engine` : undefined}
      className={cn(
        "flex flex-col gap-1 rounded-md border px-2.5 py-2 transition-colors",
        disabled
          ? "cursor-not-allowed border-border/40 bg-surface-2/10 opacity-55"
          : "border-border/50 bg-surface-2/25 hover:border-border"
      )}
    >
      <div className="flex items-center gap-2">
        {disabled ? <Lock className="size-3.5 text-quiet/60" /> : <StatusIcon status={row.status} />}
        <span className="font-mono text-[11.5px] font-medium text-foreground">{row.source}</span>
        {row.tier === "tier1" && <span className="text-[9px] text-warn">LOW-CONF</span>}
        <div className="ml-auto flex items-center gap-2">
          {!disabled && row.connected && <TrustBar score={row.trust_score} />}
          {disabled ? (
            <Badge variant="outline" className="text-[9px]">
              key needed
            </Badge>
          ) : (
            <Badge variant={statusBadgeVariant(row.status)} className="text-[9px]">
              {row.freshness_label}
            </Badge>
          )}
        </div>
      </div>
      <p className="pl-5 text-[11px] leading-relaxed text-muted">{row.review}</p>
    </div>
  );
}

// ── one category card: composite index + freshness + review + its source pickers ──
function CategoryCard({ cat }: { cat: ScoreCategory }) {
  return (
    <Card className={cn(!cat.connected && "opacity-90")}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-[13px]">
          <span className="flex items-center gap-1.5">
            {cat.label}
            {!cat.connected && (
              <Badge variant="outline" className="text-[9px]">
                offline
              </Badge>
            )}
          </span>
          <span className="flex items-baseline gap-1">
            <IndexValue score={cat.index_score} className="text-[18px]" />
            <span className="text-[10px] text-quiet">/100</span>
          </span>
        </CardTitle>
        <div className="flex items-center justify-between gap-2">
          <Badge variant={statusBadgeVariant(cat.status)} className="text-[9.5px]">
            {cat.freshness_label}
          </Badge>
          <span className="text-[10px] text-quiet">
            {cat.live_sources}/{cat.total_sources} live
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-[11.5px] leading-relaxed text-muted">{cat.review}</p>
        {cat.sources.length > 0 ? (
          <div className="space-y-1.5">
            {cat.sources.map((s) => (
              <SourceRow key={s.source} row={s} />
            ))}
          </div>
        ) : (
          <p className="text-[11px] italic text-quiet">No source wired yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

export function ScoresCockpit({ scores }: { scores: ScoresResponse }) {
  return (
    <div className="space-y-5">
      {/* Composite INDEX headline */}
      <Card>
        <CardContent className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:gap-6">
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-full border border-border/70 bg-surface-2/40">
              <Gauge className={cn("size-5", gradeColor(scores.composite_index))} />
            </div>
            <div className="leading-none">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">Composite INDEX</div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <IndexValue score={scores.composite_index} className="text-[30px]" />
                <span className="text-[12px] text-quiet">/100</span>
                <Badge variant={scores.composite_index == null ? "outline" : statusBadgeVariant("fresh")} className="ml-1 text-[9.5px] capitalize">
                  {scores.composite_status}
                </Badge>
              </div>
            </div>
          </div>
          <p className="text-[12px] leading-relaxed text-muted sm:flex-1">{scores.composite_review}</p>
        </CardContent>
      </Card>

      {/* Category grid */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {scores.categories.map((cat) => (
          <CategoryCard key={cat.key} cat={cat} />
        ))}
      </div>

      <p className="flex items-center gap-1.5 text-[11px] text-quiet">
        <Plug className="size-3" />
        Index = freshness × realized gate contribution, net of any source with no data. A source is greyed when its key isn&apos;t set on the engine. Nothing fabricated.
      </p>
    </div>
  );
}
