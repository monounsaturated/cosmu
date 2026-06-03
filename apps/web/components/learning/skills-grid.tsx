// module: SkillsGrid — surfaces GET /skills, the distilled, reusable skill recipes the brain has
// learned (Deliverable #3, the flywheel made visible). Each card shows the recipe name, a letter
// grade derived deterministically from its numeric grade, how many times it has worked, its
// lineage, and a one-line recipe summary. Server component — pure render over real engine data;
// honest empty state when the brain hasn't distilled any recipe yet.

import type { Skill } from "@/app/data";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";

// Deterministic letter from the numeric grade (0..1). No magic thresholds beyond conventional
// grade bands; purely for at-a-glance ranking, never a gate.
function letterGrade(grade: number): { letter: string; variant: "up" | "info" | "warn" | "muted" } {
  if (grade >= 0.9) return { letter: "A", variant: "up" };
  if (grade >= 0.75) return { letter: "B", variant: "info" };
  if (grade >= 0.6) return { letter: "C", variant: "warn" };
  return { letter: "D", variant: "muted" };
}

export function SkillsGrid({ skills }: { skills: Skill[] }) {
  if (!skills || skills.length === 0) {
    return (
      <EmptyState
        title="No distilled skills yet."
        hint="As the brain finds patterns that keep surviving the Gate, it distills them into reusable recipes here — each with a grade and a running success count."
      />
    );
  }

  // Highest grade first; the most-trusted recipes lead.
  const ordered = [...skills].sort((a, b) => b.grade - a.grade);

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {ordered.map((skill) => {
        const g = letterGrade(skill.grade);
        return (
          <div
            key={skill.name}
            className="flex flex-col gap-2 rounded-md border border-border/60 bg-surface-2/30 p-3.5"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-foreground">{skill.name}</div>
                <div className="truncate text-[11px] text-quiet">{skill.lineage}</div>
              </div>
              <Badge variant={g.variant} className="shrink-0" title={`grade ${skill.grade.toFixed(2)}`}>
                {g.letter}
              </Badge>
            </div>
            <p className="text-[12px] leading-relaxed text-muted">{skill.recipe_summary}</p>
            <div className="mt-auto flex items-center justify-between pt-1 text-[11px] text-quiet">
              <span className="tabular">
                {skill.success_count} {skill.success_count === 1 ? "win" : "wins"}
              </span>
              <span>{new Date(skill.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
