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

import { ArrowLeft, FlaskConical, Target } from "lucide-react";
import Link from "next/link";
import { getExperiments, engineConfigured } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { MetricCard, GaugeBar } from "@/components/ui/viz";
import { NotConnected } from "@/components/ui/honest-state";
import {
  decaysOutOfSample,
  DSR_BAR,
  DsrGauge,
  fmtDsr,
  VerdictPill
} from "@/components/theories/theory-bits";
import { TheoryList } from "./theory-list";

export default async function TheoriesPage() {
  const { experiments, connected } = await getExperiments();
  const { summary, theories } = experiments;
  const sources = Array.from(new Set(theories.map((t) => t.source))).sort();

  // How many in-sample-promising theories the honest holdout killed. This is the machine "never
  // lying": it tells on its own backtests when they don't survive out of sample.
  const decayedCount = theories.filter(decaysOutOfSample).length;
  // The best deflated-Sharpe any theory has reached, against the 0.95 Gate bar — the closest the
  // machine has ever come to a real edge.
  const best = theories.reduce<{ dsr: number; theory: (typeof theories)[number] | null }>(
    (m, t) =>
      Number.isFinite(t.best_dsr) && t.best_dsr > m.dsr ? { dsr: t.best_dsr, theory: t } : m,
    { dsr: 0, theory: null }
  );
  const bestDsr = best.dsr;
  const survivalRate = summary.total > 0 ? (summary.passed / summary.total) * 100 : 0;
  const survivalLabel =
    summary.total > 0
      ? `${survivalRate.toFixed(survivalRate > 0 && survivalRate < 1 ? 1 : 0)}% survival rate`
      : undefined;

  return (
    <div className="mx-auto max-w-[1100px] space-y-5 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      {/* ── Header ──────────────────────────────────────────────────────────────────────── */}
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
                <Badge variant="up">{summary.passed.toLocaleString()} passed</Badge>
                <Badge variant="muted">{summary.failed.toLocaleString()} failed</Badge>
              </div>
            ) : null
          }
          className="flex-1"
        />
      </div>

      {/* Plain framing, shown only when there is a ledger to frame: a long wall of killed theories is
          the proof the Gate is real, not an embarrassment. The not-connected / empty states own their
          own copy below. */}
      {connected && summary.total > 0 ? (
        <p className="max-w-2xl text-[12.5px] leading-relaxed text-muted">
          This is the machine&apos;s honest memory — every pre-registered hypothesis, with the
          Gate&apos;s verdict, the deflated Sharpe it reached against the {DSR_BAR} bar, and whether
          the edge survived out of sample. A wall of failures is the receipt that the Gate is real.
          Nothing here is fabricated.
        </p>
      ) : null}

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
                on it — PASS or FAIL, with the candidate cohort, the deflated Sharpe against the{" "}
                {DSR_BAR} bar, the out-of-sample holdout, and the exact reason it died.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ── Summary strip ───────────────────────────────────────────────────────────────
              The four numbers that frame the ledger. "Best deflated Sharpe" is the hero — it is the
              closest the machine has ever come to the bar — so it carries the dSR gauge inline. */}
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
                summary.passed === 0 && summary.total > 0
                  ? "0 survived — and that's the point."
                  : survivalLabel
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
              value={bestDsr > 0 ? fmtDsr(bestDsr) : "—"}
              tone={bestDsr >= DSR_BAR ? "up" : "muted"}
              hint={`Closest any theory has come to the ${DSR_BAR} bar.`}
              visual={
                bestDsr > 0 ? (
                  <GaugeBar
                    value={bestDsr}
                    max={1}
                    marker={DSR_BAR}
                    tone={bestDsr >= DSR_BAR ? "up" : "muted"}
                    height={6}
                    className="w-20"
                  />
                ) : undefined
              }
            />
          </section>

          {/* ── Closest run + source breakdown ──────────────────────────────────────────────
              A single calm rail: the named theory that came closest to the bar (the machine's high-
              water mark), and how the ledger breaks down by where the hypotheses came from. */}
          {best.theory ? (
            <Card className="border-iris/20">
              <CardContent className="flex flex-col gap-4 py-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 shrink-0 text-iris-soft">
                    <Target className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-quiet">
                      Closest to the bar
                    </div>
                    <p className="mt-1 truncate text-[13px] font-medium text-foreground">
                      {best.theory.hypothesis}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-quiet">
                      <span className="capitalize">{best.theory.source}</span>
                      {best.theory.asset ? (
                        <span className="tabular text-muted">{best.theory.asset}</span>
                      ) : null}
                      <span>{best.theory.kind.replace(/[-_]/g, " ")}</span>
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-4">
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-quiet">
                      dSR vs {DSR_BAR}
                    </span>
                    <DsrGauge value={bestDsr} passed={bestDsr >= DSR_BAR} size="md" />
                  </div>
                  <VerdictPill passed={best.theory.decision === "PASS"} />
                </div>
              </CardContent>
            </Card>
          ) : null}

          {summary.by_source.length > 1 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.07em] text-quiet">
                By source
              </span>
              {summary.by_source.map((s) => (
                <span
                  key={s.source}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-surface-2/30 px-2.5 py-1 text-[11.5px] text-muted"
                >
                  <span className="capitalize text-foreground">{s.source}</span>
                  <span className="tabular text-quiet">{s.n.toLocaleString()}</span>
                  {s.passed > 0 ? (
                    <span className="tabular text-up">· {s.passed} passed</span>
                  ) : null}
                </span>
              ))}
            </div>
          ) : null}

          {/* ── The ledger ──────────────────────────────────────────────────────────────────
              Searchable, filterable, sortable, expandable. The honest core of the surface. */}
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
