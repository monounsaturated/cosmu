// The DECAY RAIL — per-tracked-correlation IC sparklines that show STABILITY over runs. Each card is
// one feature's strongest-|IC| (asset × horizon) series from the generated CorrelationStability
// contract, oldest → newest, drawn with the shared SVG Sparkline. A correlation whose IC fades
// run-over-run is the tell a single scan can't show — so this rail is the honest counterweight to a
// strong one-shot IC.
//
// Server component: pure presentation over already-fetched `stability` series. We surface the
// strongest-magnitude tracked correlations first (the ones worth watching), and only those with ≥ 2
// points (a sparkline needs two to draw a shape — never a fake flat line). Non-causal series keep
// their plain flag so a stable-but-non-causal IC still reads as "Gate disposes", not an edge.

import type { CorrelationStability } from "@/app/data";
import { Sparkline } from "@/components/ui/viz";
import { fmtHorizon, fmtIc, IcPill, NonCausalFlag } from "./correlation-bits";

// Newest minus oldest |IC| — the run-over-run drift. Negative magnitude change => the correlation is
// decaying (fading toward zero), the signal this rail exists to surface.
function magnitudeDrift(ics: number[]): number {
  if (ics.length < 2) return 0;
  return Math.abs(ics[ics.length - 1]) - Math.abs(ics[0]);
}

function DecayCard({ t }: { t: CorrelationStability }) {
  const ics = t.history.map((p) => p.ic);
  const drift = magnitudeDrift(ics);
  const decaying = drift < -0.01;
  const strengthening = drift > 0.01;
  const latestSurvived = t.history.length > 0 ? t.history[t.history.length - 1].fdr_survived : false;
  return (
    <div className="rounded-lg border border-border/60 bg-surface-2/25 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-medium text-foreground" title={t.feature}>
            {t.feature}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-quiet">
            <span className="tabular text-muted">{t.asset}</span>
            <span className="tabular">{fmtHorizon(t.horizon)}</span>
          </div>
        </div>
        <IcPill ic={t.latest_ic} survived={latestSurvived} />
      </div>

      <div className="mt-2.5 flex items-center justify-between gap-2">
        <Sparkline
          values={ics}
          width={132}
          height={30}
          // Auto-tone reads the trajectory; we don't force it, so the line tells the truth of the move.
          ariaLabel={`IC over ${t.n_runs} runs for ${t.feature} on ${t.asset}`}
        />
        <span className="shrink-0 text-right text-[10.5px] tabular text-quiet">
          {t.n_runs} run{t.n_runs === 1 ? "" : "s"}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        {decaying ? (
          <span className="text-[10.5px] font-medium text-warn">decaying · {fmtIc(drift)} |IC|</span>
        ) : strengthening ? (
          <span className="text-[10.5px] font-medium text-up">strengthening · {fmtIc(drift)} |IC|</span>
        ) : (
          <span className="text-[10.5px] text-quiet">stable</span>
        )}
        <NonCausalFlag nonCausal={t.non_causal} />
      </div>
    </div>
  );
}

export function DecayRail({ stability, limit = 12 }: { stability: CorrelationStability[]; limit?: number }) {
  // Only series with a real shape (≥ 2 points), strongest |latest IC| first — the ones worth watching.
  const drawable = stability
    .filter((t) => t.history.length >= 2)
    .sort((a, b) => Math.abs(b.latest_ic) - Math.abs(a.latest_ic))
    .slice(0, limit);

  if (drawable.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 px-3 py-8 text-center text-[12px] text-quiet">
        No tracked correlations yet — decay sparklines appear once a (feature × asset × horizon) pair
        has been scanned across at least two runs.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {drawable.map((t) => (
        <DecayCard key={`${t.feature}·${t.asset}·${t.horizon}`} t={t} />
      ))}
    </div>
  );
}
