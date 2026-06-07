// Theories — the machine's EXPERIMENT MEMORY. Every trading theory it has ever tested, with the
// honest Gate's verdict (PASS/FAIL), drawn LIVE from the engine's `gate_verdicts` table via
// GET /research/experiments. This is the page where the machine proves it has never lied: it shows
// exactly how many theories were tested, how many survived the Gate, and — for the ones that looked
// good in-sample — whether the edge decayed out-of-sample.
//
// Server component: fetches the real ledger; the searchable/filterable/expandable list is a client
// island (theory-list.tsx). Honest "not connected" + "nothing yet" states, never fabricated numbers.

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { getExperiments, engineConfigured } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { Stat } from "@/components/ui/stat";
import { NotConnected } from "@/components/ui/honest-state";
import { TheoryList } from "./theory-list";

export default async function TheoriesPage() {
  const { experiments, connected } = await getExperiments();
  const { summary, theories } = experiments;
  const sources = Array.from(new Set(theories.map((t) => t.source))).sort();

  // The honest headline. "0 survived" is the truth right now — we say it out loud, never soften it.
  const headline =
    summary.total === 0
      ? "No theories tested yet."
      : `${summary.total.toLocaleString()} theor${summary.total === 1 ? "y" : "ies"} tested · ` +
        `${summary.passed.toLocaleString()} survived the Gate · the machine has never lied.`;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div className="flex items-start gap-3">
        <Link
          href="/"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Overview
        </Link>
        <SectionHeader
          eyebrow="theories · experiment memory"
          title="Every theory the machine has tested"
          aside={
            connected ? (
              <div className="flex items-center gap-2">
                <Badge variant="up">{summary.passed} passed</Badge>
                <Badge variant="muted">{summary.failed} failed</Badge>
              </div>
            ) : null
          }
          className="flex-1"
        />
      </div>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="The machine remembers every trading theory it has tested and the honest Gate's verdict. Connect the engine to see the live experiment memory."
        />
      ) : (
        <>
          {/* Summary strip — total / passed / failed + the honest headline. */}
          <section className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Theories tested" value={summary.total} accent="iris" />
              <Stat label="Survived the Gate" value={summary.passed} accent="up" />
              <Stat label="Failed" value={summary.failed} accent="down" />
            </div>
            <p className="text-[12.5px] leading-relaxed text-muted">{headline}</p>
            {summary.by_source.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {summary.by_source.map((s) => (
                  <span
                    key={s.source}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-surface-2/30 px-2.5 py-1 text-[11.5px] text-muted"
                  >
                    <span className="capitalize text-foreground">{s.source}</span>
                    <span className="tabular text-quiet">{s.n}</span>
                    {s.passed > 0 ? <span className="tabular text-up">· {s.passed} passed</span> : null}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          {/* The list — searchable, filterable, expandable. */}
          <Card>
            <CardContent className="pt-5">
              <TheoryList theories={theories} sources={sources} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
