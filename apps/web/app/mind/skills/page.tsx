// Full distilled skills page — all skill recipes, sortable + filterable.
// Linked from the Mind page DataPreview "View all" button.

import { ArrowLeft, BookOpen } from "lucide-react";
import Link from "next/link";
import { getSkills, engineConfigured } from "../../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { NotConnected } from "@/components/ui/honest-state";
import { SkillsTable } from "./skills-table";

export default async function SkillsPage() {
  const { skills, connected } = await getSkills();

  const gradeA = skills.filter((s) => s.grade >= 0.9).length;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div className="flex items-start gap-3">
        <Link
          href="/mind"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Mind
        </Link>
        <SectionHeader
          eyebrow="mind · skills"
          title="Distilled skills"
          aside={
            <div className="flex items-center gap-2">
              <Badge variant="muted">{skills.length} skills</Badge>
              {gradeA > 0 && <Badge variant="up">{gradeA} grade A</Badge>}
            </div>
          }
          className="flex-1"
        />
      </div>

      <p className="text-[12px] text-muted">
        Reusable skill recipes the brain has distilled — each with a grade, lineage, and running win count. The flywheel made visible.
      </p>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Distilled skills appear once the brain has found patterns that keep surviving the Gate."
        />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <SkillsTable skills={skills} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
