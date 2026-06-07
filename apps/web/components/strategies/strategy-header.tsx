// module: StrategyHeader — the ONE title block for the single-strategy detail view (the lean bar: no
// back-arrow, no redundant stack of badges). It answers, in one read: is this PROVEN (the Gate
// verdict), where does it trade (lane = asset-class · venue · timeframe), on what edge (the thesis),
// and what is the headline number — labelled UNAMBIGUOUSLY as backtest out-of-sample, never bare
// "return", so a historical number is never misread as forward performance.
//
// Server component. Every value is passed in already-derived from REAL detail fields; this component
// fabricates nothing and simply omits a chip when its value is null.

import type { ReactNode } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export function StrategyHeader({
  name,
  versionId,
  passed,
  lane,
  thesis,
  bestOos,
  action
}: {
  name: string;
  versionId: string;
  passed: boolean;
  // The lane — where this Version trades. Already-joined, real spec fields; null parts are dropped.
  lane: (string | null)[];
  thesis: string | null;
  // Headline backtest OOS %, already computed; null when no backtest has run.
  bestOos: number | null;
  // The single primary action (Launch live), rendered only when the caller decides it is offered.
  action?: ReactNode;
}) {
  const laneParts = lane.filter((p): p is string => !!p);
  return (
    <header className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2.5">
          {/* Verdict eyebrow — the deploy-readiness state, stated plainly in words + one semantic color. */}
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]",
              passed ? "border-up/35 bg-up/[0.08] text-up" : "border-down/35 bg-down/[0.08] text-down"
            )}
          >
            {passed ? <ShieldCheck className="size-3.5" /> : <ShieldAlert className="size-3.5" />}
            {passed ? "Gate passed — deploy-ready" : "Gate not passed — held"}
          </div>
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight text-foreground sm:text-[32px]">{name}</h1>
          {/* Lane — one calm line, the dot-separated coordinates of where it trades. */}
          {laneParts.length ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted">
              {laneParts.map((p, i) => (
                <span key={`${p}-${i}`} className="inline-flex items-center gap-2">
                  {i > 0 ? <span className="text-quiet/60" aria-hidden>·</span> : null}
                  <span>{p}</span>
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>

      {/* Thesis — the one-line reason this Version exists (spec rationale). */}
      {thesis ? <p className="max-w-3xl text-[13px] leading-relaxed text-muted">{thesis}</p> : null}

      {/* Identity + the honest framing of the headline number. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11.5px]">
        <span className="font-mono text-quiet">{versionId}</span>
        {bestOos !== null ? (
          <span className="text-quiet">
            <span className="text-muted">Best backtest OOS</span>{" "}
            <span className={cn("tabular font-semibold", bestOos >= 0 ? "text-up" : "text-down")}>
              {bestOos >= 0 ? "+" : ""}
              {bestOos.toFixed(1)}%
            </span>{" "}
            — historical, not forward. Forward proof accrues on the Simulation track below.
          </span>
        ) : (
          <span className="text-quiet">No backtest yet — no historical number to show.</span>
        )}
      </div>
    </header>
  );
}
