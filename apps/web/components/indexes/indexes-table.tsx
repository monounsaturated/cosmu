"use client";

// module: the Indexes screener — every operator-defined index with its current value + health at a glance, the
// row links to the index detail, and a "+ Define index" affordance opens the create form. Mirrors the strategies
// screener's calm dense style. HONEST: a never-computed index reads "never"/"—" (not 0); reliability/ freshness
// are the deterministic monitor's labels, never a forecast.

import { useState } from "react";
import Link from "next/link";
import type { IndexCard } from "@cosmu/contracts-ts";
import { cn, fmtTz } from "@/lib/utils";
import { DefineIndexForm } from "./define-index";

const KIND_LABEL: Record<string, string> = {
  single_account: "Single account",
  social_bucket: "Social bucket",
  event_topic: "Event topic",
  prompt_rubric: "Prompt rubric",
};

const FRESHNESS_BADGE: Record<string, string> = { fresh: "badge-up", stale: "badge-gold", never: "badge-muted" };
const RELIABILITY_BADGE: Record<string, string> = {
  stable: "badge-up", moderate: "badge-iris", volatile: "badge-dn", untested: "badge-muted",
};
const STATUS_BADGE: Record<string, string> = { active: "badge-up", paused: "badge-gold", draft: "badge-muted" };

function Badge({ map, value, tip }: { map: Record<string, string>; value: string; tip?: string }) {
  return (
    <span className={cn("badge", map[value] ?? "badge-muted")} style={{ textTransform: "capitalize" }} data-tip={tip}>
      {value}
    </span>
  );
}

export function IndexesTable({ indexes }: { indexes: IndexCard[] }) {
  const [defining, setDefining] = useState(false);

  return (
    <>
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <span className="page-title">Indexes</span>
        <span className="quiet" style={{ fontSize: 11 }}>
          Standardized, deterministically-scored signals · {indexes.length}
        </span>
        <div style={{ marginLeft: "auto" }}>
          {!defining ? (
            <button type="button" className="btn-col-picker" onClick={() => setDefining(true)}>+ Define index</button>
          ) : null}
        </div>
      </div>

      {defining ? <DefineIndexForm onClose={() => setDefining(false)} /> : null}

      {indexes.length === 0 ? (
        <div className="card">
          <div className="card-body">
            <p className="quiet" style={{ fontSize: 12, textAlign: "center", padding: "24px 4px", lineHeight: 1.6 }}>
              No indexes yet. Define one — a topic, a prompt rubric, or a bucket of social accounts. Each becomes a
              standardized point-in-time series strategies can key off. Nothing is fabricated until it computes.
            </p>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="card-body">
            <div className="tbl-scroll">
              <table className="mini-tbl">
                <thead>
                  <tr>
                    <th>Index</th>
                    <th>Kind</th>
                    <th className="r" data-tip="The latest scored value of this index (its current reading).">Value</th>
                    <th data-tip="How recent the last computed point is, vs the index's own cadence.">Freshness</th>
                    <th data-tip="Ranking stability — the spread of recent values. Stable = trustworthy to build on.">Reliability</th>
                    <th className="r" data-tip="How many strategies key off this index as a feature.">Used by</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {indexes.map((idx) => (
                    <tr key={idx.id}>
                      <td>
                        <Link href={`/indexes/${idx.id}`} className="cell-name" style={{ textDecoration: "none" }}>
                          {idx.name}
                        </Link>
                        <div className="quiet" style={{ fontSize: 9.5 }}>{idx.metric}{idx.market_wide ? " · market-wide" : ` · ${idx.entities.join(", ")}`}</div>
                      </td>
                      <td><span className="badge badge-run" style={{ textTransform: "none" }}>{KIND_LABEL[idx.kind] ?? idx.kind}</span></td>
                      <td className="r tab">
                        {idx.health.latest_value === null ? <span className="quiet">—</span> : idx.health.latest_value.toFixed(3)}
                      </td>
                      <td><Badge map={FRESHNESS_BADGE} value={idx.health.freshness}
                        tip={idx.health.latest_at ? `last point ${fmtTz(idx.health.latest_at, { dateStyle: "medium", timeStyle: "short" })}` : "never computed yet"} /></td>
                      <td>
                        <Badge map={RELIABILITY_BADGE} value={idx.health.reliability}
                          tip={idx.health.stability !== null ? `recent-value stdev ${idx.health.stability.toFixed(3)} over ${idx.health.n_points} points` : "needs ≥3 points to assess"} />
                      </td>
                      <td className="r tab">{idx.n_strategies_using || <span className="quiet">0</span>}</td>
                      <td><Badge map={STATUS_BADGE} value={idx.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
