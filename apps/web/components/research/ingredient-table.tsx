"use client";

// module: IngredientTable — the population-wide building-block (ingredient) leaderboard for the Composition
// surface. Ranks every signal/filter/exit/sizing block by how often it survived the Gate ("funded rate"),
// using the SAME collapse-on-demand ("See all / Show less") affordance the live/paper position cards use:
// a calm summary (top N) that drops down to the full list on click. Observational ONLY — recurrence and
// funded-rate are population statistics, never a funder and never a forecast.
//
// HONESTY: available:false (registry migration not applied) and the empty case both render plain language,
// never a fabricated ingredient. Every number is a real count off the engine's block registry.

import { useState } from "react";
import type { BlockStat } from "@cosmu/contracts-ts";
import { cn } from "@/lib/utils";

const LIM = 8;

const KIND_LABEL: Record<string, string> = {
  signal: "Signal",
  filter: "Filter",
  setup: "Setup",
  exit: "Exit",
  sizing: "Sizing",
};

function FundBar({ stat }: { stat: BlockStat }) {
  const rate = Number.isFinite(stat.funded_rate) ? Math.max(0, Math.min(1, stat.funded_rate)) : 0;
  const col = rate >= 0.5 ? "var(--up)" : rate > 0 ? "var(--iris)" : "var(--muted)";
  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 110 }}
      data-tip={`${stat.n_funded} of ${stat.n_versions} Versions carrying this block were funded by the Gate`}
    >
      <div className="fund-bar">
        <i style={{ width: `${rate * 100}%`, background: col }} />
      </div>
      <span className="tab" style={{ fontSize: 11, minWidth: 30, textAlign: "right" }}>
        {(rate * 100).toFixed(0)}%
      </span>
    </div>
  );
}

export function IngredientTable({ available, rows }: { available: boolean; rows: BlockStat[] }) {
  const [open, setOpen] = useState(false);

  if (!available) {
    return (
      <p className="quiet" style={{ fontSize: 11.5, lineHeight: 1.6 }}>
        The block registry is not active yet. Apply the <span className="mono">strategy_blocks</span> migration on the
        store and the building-block leaderboard appears here — which ingredients recur across the population and how
        often each one survives the Gate. Nothing is fabricated until then.
      </p>
    );
  }

  if (rows.length === 0) {
    return (
      <p className="quiet" style={{ fontSize: 11.5 }}>
        No building blocks recorded yet — they accrue as the Lab authors and screens cohorts.
      </p>
    );
  }

  const sorted = [...rows].sort((a, b) => b.funded_rate - a.funded_rate || b.n_versions - a.n_versions);
  const shown = open ? sorted : sorted.slice(0, LIM);
  const hasMore = sorted.length > LIM;

  return (
    <div className={cn("card", open && "dash-open")} style={{ marginTop: 0 }}>
      <div className="card-hdr">
        <span className="card-lbl">Ingredients · {sorted.length}</span>
        {hasMore ? (
          <button type="button" className="seeall-btn" onClick={() => setOpen((v) => !v)}>
            {open ? "Show less" : `See all ${sorted.length} →`}
          </button>
        ) : null}
      </div>
      <div className="card-body">
        <div className="tbl-scroll">
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>Block</th>
                <th>Ingredient</th>
                <th className="r" data-tip="How many Versions across the population use this exact block (param-name-invariant content hash).">Used in</th>
                <th className="r" data-tip="How many of those Versions the deterministic Gate funded.">Funded</th>
                <th data-tip="Funded ÷ Used. The share of strategies carrying this ingredient that survived the Gate. Observational — recurrence never funds a strategy; the FDR Gate alone does.">Funded rate</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <tr key={b.block_hash}>
                  <td>
                    <span className="badge badge-run" style={{ textTransform: "none" }}>
                      {KIND_LABEL[b.kind] ?? b.kind}
                    </span>
                  </td>
                  <td className="block-val" style={{ fontSize: 11 }}>
                    {b.label}
                  </td>
                  <td className="r tab">{b.n_versions}</td>
                  <td className="r tab">{b.n_funded}</td>
                  <td>
                    <FundBar stat={b} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
