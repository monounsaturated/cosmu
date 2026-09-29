"use client";

// module: RegistryBlocks — the per-Version composition view that goes one layer DEEPER than the spec-derived
// SpecBlocks (Signal/Filter/Exit/Sizing). It calls GET /blocks/version/{id} to show, for each of THIS
// Version's building blocks, how often that exact ingredient (param-name-invariant content hash) recurs
// across the population and how often it survived the Gate ("funded rate") — plus the OTHER strategies that
// share blocks with it (mix-and-match lineage). Lazy + client-fetched so it never blocks the sheet paint.
//
// HONESTY: observational only — funded-rate is "how many sharing Versions the Gate funded", never a forecast
// and never a funder. When the strategy_blocks migration isn't applied the engine returns available:false and
// we say so plainly. A registry/engine miss stays QUIET (the SpecBlocks picture above is still the real shape)
// rather than shouting an error. No fabricated rows, ever.

import { useEffect, useState } from "react";
import Link from "next/link";
import type { BlockStat, SimilarVersion, VersionBlocksResponse } from "@cosmu/contracts-ts";
import { engineGetJson } from "@/lib/engine";
import { cn } from "@/lib/utils";

const KIND_LABEL: Record<string, string> = {
  signal: "Signal",
  filter: "Filter",
  setup: "Setup",
  exit: "Exit",
  sizing: "Sizing",
};

const STATUS_BADGE: Record<string, string> = {
  live: "badge-up",
  paper: "badge-iris",
  forward_test: "badge-iris",
  killed: "badge-dn",
};

// A thin horizontal funded-rate bar: the share of Versions carrying this block that the Gate funded.
function FundBar({ stat }: { stat: BlockStat }) {
  const rate = Number.isFinite(stat.funded_rate) ? Math.max(0, Math.min(1, stat.funded_rate)) : 0;
  const col = rate >= 0.5 ? "var(--up)" : rate > 0 ? "var(--iris)" : "var(--muted)";
  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 92 }}
      data-tip={`${stat.n_funded}/${stat.n_versions} Versions carrying this block were funded by the Gate`}
    >
      <div className="fund-bar">
        <i style={{ width: `${rate * 100}%`, background: col }} />
      </div>
      <span className="tab quiet" style={{ fontSize: 10 }}>
        {(rate * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function SimilarRow({ s }: { s: SimilarVersion }) {
  return (
    <Link href={`/strategies?v=${s.version_id}`} className="similar-row" data-tip={`Shares ${s.shared_blocks} building block${s.shared_blocks === 1 ? "" : "s"} with this strategy`}>
      <span className="similar-name">{s.name}</span>
      <span className="similar-meta">
        <span className={cn("badge", STATUS_BADGE[s.status] ?? "badge-muted")} style={{ textTransform: "capitalize" }}>
          {s.status}
        </span>
        <span className="quiet tab" style={{ fontSize: 10 }}>
          {s.shared_blocks} shared
        </span>
      </span>
    </Link>
  );
}

export function RegistryBlocks({ versionId }: { versionId: string }) {
  const [data, setData] = useState<VersionBlocksResponse | null>(null);
  const [state, setState] = useState<"loading" | "error" | "done">("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setData(null);
    engineGetJson<VersionBlocksResponse>(`/blocks/version/${versionId}`)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setState("done");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  if (state === "loading") return <div className="skel" style={{ height: 56, marginTop: 8 }} />;
  // A registry/engine miss is non-fatal: the spec-derived blocks above are still the real composition.
  if (state === "error" || !data) return null;

  if (!data.available) {
    return (
      <p className="quiet" style={{ fontSize: 10.5, marginTop: 8, lineHeight: 1.5 }}>
        Registry stats are off — apply the <span className="mono">strategy_blocks</span> migration to see how often each
        ingredient survives the Gate and which strategies share them.
      </p>
    );
  }

  const blocks = [...data.blocks].sort((a, b) => b.funded_rate - a.funded_rate || b.n_versions - a.n_versions);

  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {blocks.length > 0 ? (
        <div className="tbl-scroll">
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>Block</th>
                <th>Ingredient</th>
                <th className="r" data-tip="How many Versions across the whole population use this exact block (param-name-invariant).">Used in</th>
                <th data-tip="Share of those Versions the deterministic Gate funded. Observational — never a funder.">Funded rate</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map((b) => (
                <tr key={b.block_hash}>
                  <td>
                    <span className="badge badge-run" style={{ textTransform: "none" }}>
                      {KIND_LABEL[b.kind] ?? b.kind}
                    </span>
                  </td>
                  <td className="block-val" style={{ fontSize: 10.5 }}>
                    {b.label}
                  </td>
                  <td className="r tab">{b.n_versions}</td>
                  <td>
                    <FundBar stat={b} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div>
        <div className="psec-title" style={{ marginBottom: 6 }}>
          Similar strategies <span className="quiet" style={{ fontWeight: 400, textTransform: "none" }}>· by shared blocks</span>
        </div>
        {data.similar.length === 0 ? (
          <p className="quiet" style={{ fontSize: 11 }}>
            No other strategy shares these building blocks yet.
          </p>
        ) : (
          <div className="similar-list">
            {data.similar.map((s) => (
              <SimilarRow key={s.version_id} s={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
