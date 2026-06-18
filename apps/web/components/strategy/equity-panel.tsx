"use client";

// module: EquityPanel — the SINGLE equity box on the strat sheet (v18 `Equity — Live` design). It replaces
// the two stacked boxes (a standalone "Backtest equity" + a standalone "Equity — marked value") with ONE
// `.psec` box whose `.eq-head` carries a `.seg-sm` phase toggle (Backtest · Paper/Live). Selecting a tab swaps
// the rendered series — like the v18 mockup's segmented BACKTEST / PAPER / LIVE control.
//
// HONESTY: the tabs are built ONLY from series that actually exist, never fabricated:
//   • Backtest → the engine's gross/net curve (GET /explorer/{versionId}); shown whenever there's a Version.
//     EXCEPTION — when the sheet is focused on ONE (algo × asset × venue) CELL (`perCell`), the /explorer
//     curve is the POOLED panel, NOT this cell's standalone trajectory (and for a brut-converted combo it can
//     be empty / carry a garbage pooled max_dd). There is no per-cell curve endpoint yet, so rather than draw
//     the pooled curve (or its 505%-style garbage) we show an HONEST per-cell empty state.
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
  stage,
  perCell = false
}: {
  versionId: string | null;
  forwardCurve: Point[];
  stage: Stage;
  // True when the sheet is focused on ONE cell — suppress the POOLED /explorer curve (no per-cell curve exists
  // yet) and show an honest per-cell empty state on the Backtest tab instead of garbage.
  perCell?: boolean;
}) {
  // Tabs honestly reflect available data: Backtest (whenever a Version exists, the curve is fetched lazily —
  // unless focused on one cell, where the pooled curve isn't this cell's truth, so the tab shows an honest
  // empty), plus a single forward tab labeled by the current stage when ≥ 2 marked snapshots exist.
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
        perCell ? (
          <div className="eq-empty">
            Per-cell equity curve accrues as this combo trades — the pooled backtest curve is not this cell&apos;s standalone trajectory.
          </div>
        ) : (
          <BacktestEquity versionId={versionId} embedded />
        )
      ) : (
        <PhasedEquity paperCurve={forwardCurve} embedded />
      )}
    </div>
  );
}
