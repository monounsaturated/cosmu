"use client";

// module: EquityPanel — the SINGLE equity box on the strat sheet (v18 `Equity — Live` design). It replaces
// the two stacked boxes (a standalone "Backtest equity" + a standalone "Equity — marked value") with ONE
// `.psec` box whose `.eq-head` carries a `.seg-sm` phase toggle (Backtest · Paper/Live). Selecting a tab swaps
// the rendered series — like the v18 mockup's segmented BACKTEST / PAPER / LIVE control.
//
// HONESTY: the tabs are built ONLY from series that actually exist, never fabricated:
//   • Backtest → the engine's gross/net curve (GET /explorer/{versionId}); shown whenever there's a Version.
//   • Paper / Live → the engine's MARKED scope='track' trajectory (forward_equity). There is NO paper-vs-live
//     split on the contract, so this is ONE real curve, labeled by the track's current stage (Paper or Live).
//     The tab only appears with ≥ 2 marked points; otherwise the Backtest curve is the honest view.
// Default selection = the most-advanced phase that has data (forward over backtest), matching v18.

import { useMemo, useState } from "react";
import type { Point } from "@cosmu/contracts-ts";
import type { Stage } from "./stage-control";
import { BacktestEquity } from "./backtest-equity";
import { PhasedEquity } from "./phased-equity";

type TabKey = "backtest" | "paper" | "live";

export function EquityPanel({
  versionId,
  forwardCurve,
  stage
}: {
  versionId: string | null;
  forwardCurve: Point[];
  stage: Stage;
}) {
  // Tabs honestly reflect available data: Backtest (whenever a Version exists, the curve is fetched lazily),
  // plus a single forward tab labeled by the current stage when ≥ 2 marked snapshots exist.
  const tabs = useMemo(() => {
    const t: { key: TabKey; label: string }[] = [];
    if (versionId) t.push({ key: "backtest", label: "Backtest" });
    if (forwardCurve.length >= 2) {
      const live = stage === "live";
      t.push({ key: live ? "live" : "paper", label: live ? "Live" : "Paper" });
    }
    return t;
  }, [versionId, forwardCurve.length, stage]);

  // Honor an explicit pick; otherwise default to the most-advanced phase available (last in the list).
  const [picked, setPicked] = useState<TabKey | null>(null);
  const active = picked && tabs.some((t) => t.key === picked) ? picked : tabs[tabs.length - 1]?.key ?? null;

  if (tabs.length === 0 || active === null) return null;

  const activeLabel = tabs.find((t) => t.key === active)?.label ?? "";

  return (
    <div className="psec">
      <div className="eq-head">
        <span className="eq-title-txt">Equity — {activeLabel}</span>
        {tabs.length > 1 ? (
          <div className="seg-sm" role="tablist">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={t.key === active}
                className={t.key === active ? "on" : ""}
                onClick={() => setPicked(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {active === "backtest" && versionId ? (
        <BacktestEquity versionId={versionId} embedded />
      ) : (
        <PhasedEquity paperCurve={forwardCurve} embedded />
      )}
    </div>
  );
}
