// The Mind — one destination that answers, in one vocabulary: what the agent KNOWS (its data sources), how it
// THINKS (the analyst panel debating a market read), and what it has LEARNED (memory, the ML model, regimes,
// gate efficiency). A reasoning surface only: the railguard is shown up front — it reasons, it never moves
// money. The deterministic gate alone disposes.
//
// Layout (premium/pro/lean): the consensus read leads; the data-source catalog ("what it knows") is a
// scannable coverage rollup + grouped feeds; secondary detail (scores, source trust, learnings) lives in
// one focused tab strip so the operator reads one section at a time, never a wall.
// Honest: a source with no data shows "no data" — never fabricated.

import Link from "next/link";
import { BookOpen, Brain, Database, Gauge, GraduationCap, ShieldCheck, Star } from "lucide-react";
import { getMind, getScores, getSkills, getSourceTrust, getNewsIntel, engineConfigured } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { NotConnectedBanner } from "@/components/ui/honest-state";
import { Tabs } from "@/components/ui/viz";
import { AnalystPanel } from "@/components/mind/analyst-panel";
import { MindKnows } from "@/components/mind/mind-knows";
import { MindLearnings } from "@/components/mind/mind-learnings";
import { MemoryInsights } from "@/components/learning/memory-insights";
import { SkillsGrid } from "@/components/learning/skills-grid";
import { ScoresCockpit } from "@/components/scores/scores-cockpit";
import { SourceTrustScoreboard } from "@/components/mind/source-trust-scoreboard";
import { NewsIntelPanel } from "@/components/mind/news-intel-panel";
import { DataPreview } from "@/components/ui/data-preview";

export default async function MindPage() {
  const [{ mind, connected }, { scores }, { skills }, { trust }, { intel }] = await Promise.all([
    getMind(),
    getScores(),
    getSkills(),
    getSourceTrust(),
    getNewsIntel("BTCUSDT", 20),
  ]);

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-9 lg:px-7">
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

      {/* HOW IT THINKS — the analyst panel + the debate's consensus. The lead: one market read. */}
      <section className="space-y-3">
        <SectionHeader
          eyebrow="how it thinks"
          title={
            <span className="flex items-center gap-2 text-base">
              <Brain className="size-4 text-iris-soft" /> The analyst panel
            </span>
          }
        />
        <AnalystPanel mind={mind} />
      </section>

      {/* WHAT IT KNOWS — the data-source catalog: a coverage rollup, then feeds grouped by perspective. */}
      <section className="space-y-3">
        <SectionHeader
          eyebrow="what it knows"
          title={
            <span className="flex items-center gap-2 text-base">
              <Database className="size-4 text-iris-soft" /> Data-source catalog
            </span>
          }
          aside={
            <Link
              href="/mind/sources"
              className="text-[12px] font-medium text-iris-soft transition-colors hover:text-iris"
            >
              Trust scoreboard →
            </Link>
          }
        />
        <MindKnows knows={mind.knows} />
      </section>

      {/* SECONDARY DETAIL — scores, source trust + news, and learnings. One focused tab at a time
          (replaces a single mega "show more" that dumped every section at once). */}
      <section className="space-y-3">
        <SectionHeader eyebrow="detail" title={<span className="text-base">Scores, trust &amp; learnings</span>} />
        <Tabs
          ariaLabel="Mind detail"
          tabs={[
            {
              id: "scores",
              label: (
                <span className="flex items-center gap-1.5">
                  <Gauge className="size-3.5" /> Scores
                </span>
              ),
              count: scores.categories.length,
              content: (
                <div className="space-y-3">
                  <p className="text-[12px] leading-relaxed text-muted">
                    Composite + per-category INDEX scores (e.g. regulatory risk, risk-on/off), each with a plain-language
                    review and freshness. A key-gated source with no key is greyed — never fabricated.
                  </p>
                  <ScoresCockpit scores={scores} />
                </div>
              ),
            },
            {
              id: "trust",
              label: (
                <span className="flex items-center gap-1.5">
                  <Star className="size-3.5" /> Source trust &amp; news
                </span>
              ),
              count: trust.rows.length,
              content: (
                <div className="space-y-3">
                  <p className="text-[12px] leading-relaxed text-muted">
                    Trust = freshness × realized gate contribution. Honest: sources with no data show &quot;no data&quot;.
                    Never fabricated.
                  </p>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <DataPreview href="/mind/sources" viewAllLabel="View all sources" total={trust.rows.length}>
                      <SourceTrustScoreboard rows={trust.rows.slice(0, 5)} asOf={trust.as_of} />
                    </DataPreview>
                    <NewsIntelPanel events={intel.events} symbol={intel.symbol} />
                  </div>
                </div>
              ),
            },
            {
              id: "learned",
              label: (
                <span className="flex items-center gap-1.5">
                  <GraduationCap className="size-3.5" /> What it has learned
                </span>
              ),
              content: (
                <div className="space-y-3">
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
                        <DataPreview href="/mind/skills" viewAllLabel="View all skills" total={skills.length}>
                          <SkillsGrid skills={skills.slice(0, 6)} />
                        </DataPreview>
                      </CardContent>
                    </Card>
                  </div>
                </div>
              ),
            },
          ]}
        />
      </section>
    </div>
  );
}
