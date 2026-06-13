"use client";

// Source credibility table — the voice scoreboard: every pre-registered voice's resolved-call record.
// Honest rendering rules: a null metric is UNTESTED (no resolved claims yet) and renders as an em-dash
// with a muted "untested" hint — NEVER as 0 (a zero would read as "tested and unskilled"). The empty
// panel explains pre-registration instead of pretending data exists.

import { MicOff } from "lucide-react";
import type { CredibilityRow } from "@cosmu/contracts-ts";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";
import { cn } from "@/lib/utils";

const UNTESTED_HINT = "untested — no resolved claims yet";

// The one honest null cell: an em-dash with the muted "untested" hint. Never renders 0 for a null.
function Untested() {
  return (
    <span className="text-[12px] text-quiet" title={UNTESTED_HINT}>
      — <span className="text-[9.5px] uppercase tracking-[0.06em] text-quiet/70">untested</span>
    </span>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function PlatformChip({ platform }: { platform: string }) {
  return (
    <Badge variant={platform === "x" ? "iris" : platform === "reddit" ? "warn" : "muted"} className="text-[9.5px] uppercase">
      {platform}
    </Badge>
  );
}

const COLUMNS: ColumnDef<CredibilityRow>[] = [
  {
    key: "handle",
    label: "Voice",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => (
      <div className="flex items-center gap-2">
        <span className="font-mono text-[12px] font-medium text-foreground">{r.handle}</span>
        <PlatformChip platform={r.platform} />
      </div>
    )
  },
  {
    key: "n_posts",
    label: "Posts",
    sortable: true,
    align: "right",
    renderCell: (r) => <span className="tabular text-[12px] text-muted">{r.n_posts}</span>
  },
  {
    key: "n_claims",
    label: "Claims",
    sortable: true,
    align: "right",
    renderCell: (r) => <span className="tabular text-[12px] text-muted">{r.n_claims}</span>
  },
  {
    key: "n_resolved",
    label: "Resolved",
    sortable: true,
    align: "right",
    renderCell: (r) => (
      <span className={cn("tabular text-[12px]", r.n_resolved > 0 ? "text-foreground" : "text-quiet")}>
        {r.n_resolved}
      </span>
    )
  },
  {
    key: "hit_rate",
    label: "Hit vs base",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      if (r.hit_rate === null || r.hit_rate === undefined) return <Untested />;
      const beatsBase = r.base_hit_rate !== null && r.base_hit_rate !== undefined && r.hit_rate > r.base_hit_rate;
      return (
        <span className="tabular text-[12px]">
          <span className={beatsBase ? "text-up" : "text-foreground"}>{pct(r.hit_rate)}</span>
          {r.base_hit_rate !== null && r.base_hit_rate !== undefined && (
            <span className="text-quiet"> vs {pct(r.base_hit_rate)}</span>
          )}
        </span>
      );
    }
  },
  {
    key: "brier_skill_score",
    label: "Brier skill",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      const v = r.brier_skill_score;
      if (v === null || v === undefined) return <Untested />;
      return (
        <span className={cn("tabular text-[12px]", v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted")}>
          {v > 0 ? "+" : ""}{v.toFixed(2)}
        </span>
      );
    }
  },
  {
    key: "calibration_error",
    label: "Calibration",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      const v = r.calibration_error;
      if (v === null || v === undefined) return <Untested />;
      return <span className="tabular text-[12px] text-muted">{v.toFixed(2)}</span>;
    }
  },
  {
    key: "skill",
    label: "Skill",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      const v = r.skill;
      if (v === null || v === undefined) return <Untested />;
      return (
        <span className={cn("tabular text-[12px] font-medium", v >= 0.6 ? "text-up" : v >= 0.4 ? "text-foreground" : "text-warn")}>
          {v.toFixed(2)}
        </span>
      );
    }
  },
  {
    key: "authority",
    label: "Authority",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      const v = r.authority;
      if (v === null || v === undefined) return <Untested />;
      return <span className="tabular text-[12px] text-muted">{v.toFixed(2)}</span>;
    }
  },
  {
    key: "primacy_rate",
    label: "Primacy",
    sortable: true,
    align: "right",
    renderCell: (r) => {
      const v = r.primacy_rate;
      if (v === null || v === undefined) return <Untested />;
      return <span className="tabular text-[12px] text-muted">{pct(v)}</span>;
    }
  }
];

// Sort with null = untested BELOW every real value when descending (mirrors the API's NULLS LAST).
function credibilityComparator(a: CredibilityRow, b: CredibilityRow, key: string): number {
  const av = (a as unknown as Record<string, unknown>)[key];
  const bv = (b as unknown as Record<string, unknown>)[key];
  if (typeof av === "string" || typeof bv === "string") return String(av ?? "").localeCompare(String(bv ?? ""));
  const an = typeof av === "number" ? av : -Infinity;
  const bn = typeof bv === "number" ? bv : -Infinity;
  return an === bn ? a.handle.localeCompare(b.handle) : an - bn;
}

export function VoiceCredibilityTable({ rows }: { rows: CredibilityRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No voices on the panel yet"
        hint={
          <>
            Voices are pre-registered in{" "}
            <code className="font-mono text-[10.5px] text-iris-soft">apps/engine/cosmu/config/voices.py</code> — one
            line per voice, with the WHY written before any outcome is known (the anti-survivorship discipline).
            The hourly credibility pass then pulls each voice&apos;s timeline, extracts typed claims, and fills this
            scoreboard in. Nothing here is ever fabricated.
          </>
        }
        icon={<MicOff className="size-5" />}
      />
    );
  }

  return (
    <DataTablePage
      columns={COLUMNS}
      rows={rows}
      keyOf={(r) => `${r.platform}:${r.handle}`}
      initialSort="skill"
      initialDir="desc"
      comparator={credibilityComparator}
      searchPlaceholder="Search handle, platform…"
      matchSearch={(r, q) => r.handle.toLowerCase().includes(q) || r.platform.toLowerCase().includes(q)}
      emptyLabel="No voices match the search."
    />
  );
}
