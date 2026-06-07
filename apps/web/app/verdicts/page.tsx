// Theories — the machine's EXPERIMENT MEMORY. Every trading theory it has ever tested, with the
// honest Gate's verdict (PASS/FAIL), drawn LIVE from the engine's `gate_verdicts` table via
// GET /research/experiments. This is the page where the machine proves it has never lied: it shows
// exactly how many theories were tested, how many survived the Gate, and — for the ones that looked
// good in-sample — whether the edge decayed out-of-sample.
//
// Browsing the machine's honest failures is the POINT, not an embarrassment: a wall of killed
// theories is the receipt that the Gate is real. The headline, the survival rate, and the empty
// state all say so out loud — "0 survived, and that's the point" — never softening the truth.
//
// Server component: fetches the real ledger; the searchable/filterable/expandable list is a client
// island (theory-list.tsx). Honest "not connected" + "nothing yet" states, never fabricated numbers.

import { ArrowLeft, ShieldCheck, FlaskConical } from "lucide-react";
import Link from "next/link";
import { getExperiments, engineConfigured } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { MetricCard, GaugeBar } from "@/components/ui/viz";
import { NotConnected } from "@/components/ui/honest-state";
import { TheoryList } from "./theory-list";

// A theory "decayed out-of-sample" when it looked promising in-sample (high dSR) but the holdout
// turned negative — the single most important honesty signal. Mirrors the same test in theory-list.
function decayedOutOfSample(t: { best_dsr: number; best_holdout_dsr: number | null }): boolean {
  return (
    t.best_holdout_dsr !== null &&
    Number.isFinite(t.best_holdout_dsr) &&
    t.best_holdout_dsr < 0 &&
    t.best_dsr >= 0.5
  );
}

export default async function TheoriesPage() {
  const { experiments, connected } = await getExperiments();
  const { summary, theories } = experiments;
  const sources = Array.from(new Set(theories.map((t) => t.source))).sort();

  // How many in-sample-promising theories the honest holdout killed. This is the machine "never
  // lying": it tells on its own backtests when they don't survive out of sample.
  const decayedCount = theories.filter(decayedOutOfSample).length;
  // The best deflated-Sharpe any theory has reached, against the 0.95 Gate bar — the closest the
  // machine has ever come to a real edge.
  const bestDsr = theories.reduce(
    (m, t) => (Number.isFinite(t.best_dsr) && t.best_dsr > m ? t.best_dsr : m),
    0
  );
  const survivalRate = summary.total > 0 ? (summary.passed / summary.total) * 100 : 0;

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
      ) : summary.total === 0 ? (
        // Honest, confident empty state. Zero theories is not a blank page — it's the start of the
        // ledger, and we say what it will fill with.
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
            <div className="flex size-12 items-center justify-center rounded-full border border-iris/30 bg-iris/10 text-iris-soft">
              <FlaskConical className="size-5" />
            </div>
            <div className="space-y-1.5">
              <div className="text-[15px] font-semibold text-foreground">No theories tested yet.</div>
              <p className="mx-auto max-w-md text-[12.5px] leading-relaxed text-muted">
                Every pre-registered hypothesis the machine tests lands here the moment the Gate rules
                on it — PASS or FAIL, with the candidate cohort, the deflated Sharpe against the 0.95
                bar, the out-of-sample holdout, and the exact reason it died. Nothing is fabricated.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* The confident framing: this surface is the receipt that the Gate is real. */}
          <Card className="border-iris/25">
            <CardContent className="flex items-start gap-3 py-4">
              <span className="mt-0.5 shrink-0 text-iris-soft">
                <ShieldCheck className="size-4" />
              </span>
              <p className="text-[12.5px] leading-relaxed text-muted">
                This is the machine&apos;s honest memory. A long ledger of killed theories is not a
                failure — it is the proof the Gate is real. The machine reports its own losers,
                including the in-sample edges that decayed once it looked out of sample.
                {summary.passed === 0 ? (
                  <span className="text-foreground">
                    {" "}
                    {summary.total.toLocaleString()} tested, 0 survived — and that&apos;s the point.
                  </span>
                ) : (
                  <span className="text-foreground">
                    {" "}
                    {summary.passed.toLocaleString()} of {summary.total.toLocaleString()} survived the
                    Gate.
                  </span>
                )}
              </p>
            </CardContent>
          </Card>

          {/* Summary strip — total / survived / decayed / best dSR, with inline honest visuals. */}
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label="Theories tested"
              value={summary.total.toLocaleString()}
              tone="iris"
              hint="Every pre-registered hypothesis the Gate has ruled on."
            />
            <MetricCard
              label="Survived the Gate"
              value={summary.passed.toLocaleString()}
              tone={summary.passed > 0 ? "up" : "muted"}
              hint={
                summary.total > 0
                  ? `${survivalRate.toFixed(survivalRate < 1 && survivalRate > 0 ? 1 : 0)}% survival rate`
                  : undefined
              }
            />
            <MetricCard
              label="Decayed out-of-sample"
              value={decayedCount.toLocaleString()}
              tone={decayedCount > 0 ? "warn" : "muted"}
              hint="Looked good in-sample; the honest holdout killed it."
            />
            <MetricCard
              label="Best deflated Sharpe"
              value={bestDsr > 0 ? bestDsr.toFixed(2) : "—"}
              tone={bestDsr >= 0.95 ? "up" : "muted"}
              hint="Closest any theory has come to the 0.95 bar."
              visual={
                bestDsr > 0 ? (
                  <GaugeBar
                    value={bestDsr}
                    max={1}
                    marker={0.95}
                    tone={bestDsr >= 0.95 ? "up" : "muted"}
                    height={6}
                    className="w-20"
                  />
                ) : undefined
              }
            />
          </section>

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

          {/* The list — searchable, filterable, sortable, expandable. */}
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
