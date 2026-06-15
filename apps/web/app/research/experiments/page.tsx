// Research · Experiments — the machine's EXPERIMENT MEMORY made visible. It answers the question the
// Strategies table cannot: "what has the machine actually TESTED?" The Strategies surface lists Versions
// (strategy_versions); the far larger body of tested theories lives in gate_verdicts (cohort runs) and was
// previously invisible in the app. This page binds /research/experiments — every theory run through the
// honest BH-FDR cohort Gate: the plain hypothesis, its source, the PASS/STOP verdict, the best in-sample
// deflated-Sharpe prob vs the 0.95 bar, and the REAL out-of-sample holdout dSR (high in-sample + negative
// holdout = overfit, not an edge). Read-only. HONEST: a PASS here is a genuine FDR-gated survivor, never
// fabricated; nothing tested yet renders an explicit empty state, never demo rows.

import { Suspense } from "react";
import { engineConfigured } from "../../data";
import { getExperiments, type ExperimentTheory } from "../../data/research";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { cn } from "@/lib/utils";

// On-demand: the engine may be offline at build time; the honest not-connected/empty states must reflect the
// real moment, never a baked snapshot.
export const dynamic = "force-dynamic";

// The pre-registered cohort bar (cosmu.research.gate PREREGISTERED_BAR) — a candidate must clear a deflated-
// Sharpe probability of 0.95 to be a survivor. Surfaced so each theory's best dSR is read against the bar.
const DSR_BAR = 0.95;

export default function ResearchExperimentsPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Experiments" />
            <div className="skel" style={{ height: 420 }} />
          </>
        }
      >
        <ExperimentsData />
      </Suspense>
    </Page>
  );
}

async function ExperimentsData() {
  const { experiments, connected } = await getExperiments();

  if (!connected) {
    return (
      <>
        <Toolbar title="Experiments" />
        <NotConnected
          configured={engineConfigured}
          what="The machine's experiment memory — every theory tested through the honest cohort Gate — appears here once the engine is connected. No demo rows."
        />
      </>
    );
  }

  const { summary, theories } = experiments;

  if (summary.total === 0) {
    return (
      <>
        <Toolbar title="Experiments" />
        <div className="card">
          <div className="card-body">
            <EmptyState
              title="No theories tested yet."
              hint="Each time the machine runs a cohort through the BH-FDR Gate (scan-signals, evolve, idea intake), the hypothesis and its verdict are recorded here — passed or killed, with the real out-of-sample holdout."
            />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Toolbar
        title="Experiments"
        left={
          <span className="quiet" style={{ fontSize: 12 }}>
            {summary.total} tested · {summary.passed} survived the cohort Gate
          </span>
        }
      />

      {/* KPI strip — the honest test volume the Strategies table doesn't carry. */}
      <div className="kpi-grid">
        <KBox label="Theories tested" value={summary.total} sub="cohort Gate runs (BH-FDR)" />
        <KBox label="Survived" value={summary.passed} sub={`cleared the ${DSR_BAR} dSR bar + FDR`} cls={summary.passed > 0 ? "up" : undefined} />
        <KBox label="Killed" value={summary.failed} sub="no edge after correction" />
        <KBox label="Sources" value={summary.by_source.length} sub="data axes probed" />
      </div>

      {/* Per-source breakdown — which axes the machine has probed, and how many survived each. */}
      {summary.by_source.length > 0 ? (
        <div className="card" style={{ marginBottom: "var(--gap)" }}>
          <div className="card-body">
            <div className="kpi-label" style={{ marginBottom: 8 }}>By source</div>
            <div className="tbl-scroll">
              <table className="mini-tbl">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th className="r">Tested</th>
                    <th className="r">Survived</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_source.map((s) => (
                    <tr key={s.source}>
                      <td style={{ fontWeight: 500, color: "var(--fg)" }}>{s.source}</td>
                      <td className="r tab muted">{s.n}</td>
                      <td className={cn("r tab", s.passed > 0 ? "up" : "quiet")}>{s.passed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      {/* The theories themselves — hypothesis, verdict, best dSR vs the 0.95 bar, and the REAL holdout dSR. */}
      <div className="card">
        <div className="card-body">
          <div className="kpi-label" style={{ marginBottom: 8 }}>Tested theories</div>
          <div className="tbl-scroll">
            <table className="mini-tbl">
              <thead>
                <tr>
                  <th>Hypothesis</th>
                  <th className="r">Promoted</th>
                  <th className="r">Best dSR</th>
                  <th className="r">Holdout dSR</th>
                  <th className="r">Verdict</th>
                  <th className="r">Tested</th>
                </tr>
              </thead>
              <tbody>
                {theories.map((t, i) => (
                  <TheoryRow key={t.run_id ?? `${t.ts}-${i}`} t={t} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

function TheoryRow({ t }: { t: ExperimentTheory }) {
  const passed = t.decision === "PASS";
  const clearedBar = t.best_dsr >= DSR_BAR;
  const holdout = t.best_holdout_dsr;
  return (
    <tr>
      <td>
        <span style={{ fontWeight: 500, color: "var(--fg)" }}>{t.hypothesis || "(unlabelled theory)"}</span>
        <span className="quiet" style={{ display: "block", fontSize: 9.5, marginTop: 1 }}>
          {t.source}
          {t.asset ? ` · ${t.asset}` : ""}
        </span>
      </td>
      <td className="r tab muted">
        {t.n_promoted}/{t.n_candidates}
      </td>
      <td className={cn("r tab", clearedBar ? "up" : "quiet")}>{t.best_dsr.toFixed(2)}</td>
      <td className={cn("r tab", holdout === null ? "quiet" : holdout < 0 ? "dn" : "muted")}>
        {holdout === null ? "—" : holdout.toFixed(2)}
      </td>
      <td className={cn("r tab", passed ? "up" : "quiet")} style={{ fontWeight: 600 }}>
        {t.decision}
      </td>
      <td className="r tab quiet" style={{ fontSize: 11 }}>
        {(t.ts ?? "").slice(0, 10)}
      </td>
    </tr>
  );
}

function KBox({ label, value, sub, cls }: { label: string; value: number; sub: string; cls?: string }) {
  return (
    <div className="kpi-box">
      <div className="kpi-label">{label}</div>
      <div className={cn("kpi-val tab", cls)}>{value}</div>
      <div className={cn("kpi-sub", cls ?? "muted")}>{sub}</div>
    </div>
  );
}
