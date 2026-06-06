"use client";

// Sortable + filterable skills table.

import type { Skill } from "@cosmu/contracts-ts";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";
import { BookOpen } from "lucide-react";

function letterGrade(grade: number): { letter: string; variant: "up" | "info" | "warn" | "muted" } {
  if (grade >= 0.9) return { letter: "A", variant: "up" };
  if (grade >= 0.75) return { letter: "B", variant: "info" };
  if (grade >= 0.6) return { letter: "C", variant: "warn" };
  return { letter: "D", variant: "muted" };
}

const COLUMNS: ColumnDef<Skill>[] = [
  {
    key: "name",
    label: "Skill",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => (
      <div>
        <div className="font-medium text-foreground">{r.name}</div>
        <div className="text-[11px] text-quiet">{r.lineage}</div>
      </div>
    )
  },
  {
    key: "grade",
    label: "Grade",
    sortable: true,
    renderCell: (r) => {
      const g = letterGrade(r.grade);
      return (
        <div className="flex items-center gap-2">
          <Badge variant={g.variant}>{g.letter}</Badge>
          <span className="tabular text-[11px] text-quiet">{r.grade.toFixed(2)}</span>
        </div>
      );
    }
  },
  {
    key: "success_count",
    label: "Wins",
    sortable: true,
    align: "right",
    renderCell: (r) => (
      <span className="tabular text-[12px] text-foreground">{r.success_count}</span>
    )
  },
  {
    key: "recipe_summary",
    label: "Recipe",
    renderCell: (r) => (
      <p className="text-[12px] leading-relaxed text-muted">{r.recipe_summary}</p>
    )
  },
  {
    key: "created_at",
    label: "Added",
    sortable: true,
    renderCell: (r) => (
      <span className="tabular text-[11px] text-quiet">
        {new Date(r.created_at).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric"
        })}
      </span>
    )
  }
];

export function SkillsTable({ skills }: { skills: Skill[] }) {
  if (skills.length === 0) {
    return (
      <EmptyState
        title="No distilled skills yet."
        hint="As the brain finds patterns that keep surviving the Gate, it distills them into reusable recipes here."
        icon={<BookOpen className="size-5" />}
      />
    );
  }

  return (
    <DataTablePage
      columns={COLUMNS}
      rows={skills}
      keyOf={(r) => r.name}
      initialSort="grade"
      initialDir="desc"
      searchPlaceholder="Search skill, recipe…"
      matchSearch={(r, q) =>
        r.name.toLowerCase().includes(q) ||
        r.recipe_summary.toLowerCase().includes(q) ||
        r.lineage.toLowerCase().includes(q)
      }
      emptyLabel="No skills match the search."
    />
  );
}
