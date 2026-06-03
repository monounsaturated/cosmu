// The Mind — one destination that answers, in one vocabulary: what the agent KNOWS (its data sources), how it
// THINKS (the analyst panel debating a market read), and what it has LEARNED (memory, the ML model, regimes,
// gate efficiency). A reasoning surface only: the railguard is shown up front — it reasons, it never moves
// money. The deterministic gate alone disposes.

import { BookOpen, Brain, Database, GraduationCap, ShieldCheck } from "lucide-react";
import { getMind, getSkills, engineConfigured } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import { AnalystPanel } from "@/components/mind/analyst-panel";
import { MindKnows } from "@/components/mind/mind-knows";
import { MindLearnings } from "@/components/mind/mind-learnings";
import { MemoryInsights } from "@/components/learning/memory-insights";
import { SkillsGrid } from "@/components/learning/skills-grid";

export default async function MindPage() {
  const [{ mind, connected }, { skills }] = await Promise.all([getMind(), getSkills()]);

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-8 lg:px-7">
      <SectionHeader
        eyebrow="mind"
        title="What the agent knows, thinks, and has learned"
        aside={
          <Badge variant="muted">
            <ShieldCheck className="size-3" /> Reasons · never funds
          </Badge>
        }
      />

      {!connected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      {/* HOW IT THINKS — the analyst panel + the debate's consensus */}
      <section className="space-y-3">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <Brain className="size-4 text-iris-soft" /> How it thinks
        </h3>
        <AnalystPanel mind={mind} />
      </section>

      {/* WHAT IT KNOWS — data sources grouped by perspective + freshness */}
      <section className="space-y-3">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <Database className="size-4 text-iris-soft" /> What it knows
        </h3>
        <MindKnows knows={mind.knows} />
      </section>

      {/* WHAT IT HAS LEARNED — ML, regimes, gate efficiency, memory, skills */}
      <section className="space-y-3">
        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <GraduationCap className="size-4 text-iris-soft" /> What it has learned
        </h3>
        <MindLearnings learnings={mind.learnings} />
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Dead ends &amp; winner patterns</CardTitle>
            </CardHeader>
            <CardContent>
              <MemoryInsights insights={mind.learnings.insights} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <BookOpen className="size-4 text-iris-soft" /> Distilled skills
              </CardTitle>
            </CardHeader>
            <CardContent>
              <SkillsGrid skills={skills} />
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
