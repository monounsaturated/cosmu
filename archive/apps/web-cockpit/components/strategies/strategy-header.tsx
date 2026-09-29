// module: StrategyHeader — the ONE title block for the standalone single-Version page (Iris Bento). It
// answers, in one read: the Gate verdict (proven or held), the Version name, where it trades (lane =
// venue · timeframe), the thesis, and the honest headline number — labelled UNAMBIGUOUSLY as backtest
// out-of-sample, never bare "return", so a historical number is never misread as paper performance.
//
// Server-safe. Every value is passed in already-derived from REAL detail fields; this fabricates nothing
// and simply omits a part when its value is null.

import { cn } from "@/lib/utils";

export function StrategyHeader({
  name,
  versionId,
  passed,
  lane,
  thesis,
  bestOos
}: {
  name: string;
  versionId: string;
  passed: boolean;
  // The lane — where this Version trades. Already-joined, real spec fields; null parts are dropped.
  lane: (string | null)[];
  thesis: string | null;
  // Headline backtest OOS %, already computed; null when no backtest has run.
  bestOos: number | null;
}) {
  const laneParts = lane.filter((p): p is string => !!p);
  return (
    <header style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <span className={passed ? "stage-badge sb-live" : "stage-badge sb-killed"} style={{ alignSelf: "flex-start" }}>
        {passed ? "Gate passed — deploy-ready" : "Gate not passed — held"}
      </span>
      <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.03em", color: "var(--fg)", margin: 0 }}>{name}</h1>
      {laneParts.length ? (
        <div className="muted" style={{ fontSize: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {laneParts.map((p, i) => (
            <span key={`${p}-${i}`}>
              {i > 0 ? <span className="quiet" style={{ marginRight: 8 }}>·</span> : null}
              {p}
            </span>
          ))}
        </div>
      ) : null}
      {thesis ? <p className="ai-body" style={{ maxWidth: 720 }}>{thesis}</p> : null}
      <div className="quiet" style={{ fontSize: 11, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
        <span className="mono">{versionId}</span>
        {bestOos !== null ? (
          <span>
            <span className="muted">Best backtest OOS</span>{" "}
            <span className={cn("tab", bestOos >= 0 ? "up" : "dn")} style={{ fontWeight: 600 }}>
              {bestOos >= 0 ? "+" : ""}
              {bestOos.toFixed(1)}%
            </span>{" "}
            — historical, not live-data proof.
          </span>
        ) : (
          <span>No backtest yet — no historical number to show.</span>
        )}
      </div>
    </header>
  );
}
