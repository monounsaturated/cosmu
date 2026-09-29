"use client";

// module: the fiche-triplet header. Shows the CLICKED (algo × asset × venue) cell — big and focused, with its
// own standalone P&L — plus an asset/venue selector that navigates to a SIBLING triplet (same algo, different
// asset/venue). Nothing is averaged: each cell keeps its own return/verdict; the pooled number rides along as
// advisory only. The selector only ever offers triplets that ACTUALLY exist for this algo, so a pick always
// lands on a real cell. Pairs with the comparison grid (SymbolsTable) rendered below it on the fiche.

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import type { LabSymbolRow } from "@cosmu/contracts-ts";
import { formatPct } from "@/lib/utils";
import { tripletHref, VerdictBadge } from "@/components/lab/symbols-table";

const VENUE_NONE = "—";

export function TripletCard({ cell, comparison }: { cell: LabSymbolRow | null; comparison: LabSymbolRow[] }) {
  const router = useRouter();
  const curSymbol = cell?.symbol ?? "";
  const curVenue = cell?.venue_id ?? "";

  // The asset/venue options are derived from THIS algo's real cells (comparison is already outlier-sorted, so
  // the first match for any predicate is the strongest), never a static universe — a pick can't miss.
  const symbolOptions = useMemo(() => Array.from(new Set(comparison.map((r) => r.symbol))).sort(), [comparison]);
  const venueOptions = useMemo(
    () => Array.from(new Set(comparison.map((r) => r.venue_id ?? ""))).sort(),
    [comparison],
  );

  const go = (pred: (r: LabSymbolRow) => boolean): boolean => {
    const hit = comparison.find(pred);
    if (hit) {
      router.push(tripletHref(hit));
      return true;
    }
    return false;
  };
  const onAsset = (symbol: string) => {
    // keep the venue fixed when that triplet exists, else jump to the strongest cell for the new asset
    if (!go((r) => r.symbol === symbol && (r.venue_id ?? "") === curVenue)) go((r) => r.symbol === symbol);
  };
  const onVenue = (venue: string) => {
    if (!go((r) => r.symbol === curSymbol && (r.venue_id ?? "") === venue)) go((r) => (r.venue_id ?? "") === venue);
  };

  return (
    <div className="card">
      <div className="card-hdr" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="card-lbl" data-tip="One (algo × asset × venue) cell — the granular truth, never a pooled mean. The pooled number is advisory only.">
          Triplet{cell ? ` · ${cell.symbol} · ${cell.venue_id ?? VENUE_NONE}` : ""}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <label className="quiet" style={{ fontSize: 11 }}>
            Asset{" "}
            <select
              className="search-input"
              value={curSymbol}
              onChange={(e) => onAsset(e.target.value)}
              aria-label="Switch asset (navigate to sibling triplet)"
              style={{ maxWidth: 130 }}
            >
              {curSymbol ? null : <option value="">—</option>}
              {symbolOptions.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="quiet" style={{ fontSize: 11 }}>
            Venue{" "}
            <select
              className="search-input"
              value={curVenue}
              onChange={(e) => onVenue(e.target.value)}
              aria-label="Switch venue (navigate to sibling triplet)"
              style={{ maxWidth: 130 }}
            >
              {venueOptions.map((v) => (
                <option key={v} value={v}>{v === "" ? VENUE_NONE : v}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="card-body">
        {cell === null ? (
          <p className="quiet" style={{ fontSize: 12, margin: 0 }}>
            No backtest cell for this exact triplet. Pick an asset / venue above to focus one of this strategy’s
            real cells, or choose a row in the comparison table below.
          </p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "flex-end" }}>
            <Stat
              label="Return"
              big
              value={formatPct(cell.return_pct * 100)}
              tone={cell.return_pct >= 0 ? "up" : "dn"}
              tip="The standalone, net-of-fee return on THIS asset at THIS venue — the granular truth, never a pooled mean."
            />
            <Stat
              label="Pooled (adv.)"
              dim
              value={cell.pooled_return_pct === null || cell.pooled_return_pct === undefined ? "—" : formatPct(cell.pooled_return_pct * 100)}
              tip="pooled (advisory): the parent backtest's pooled OOS return — context only, never the per-cell truth, never a verdict input, never funds."
            />
            <Stat label="Sharpe" value={Number.isFinite(cell.sharpe) ? cell.sharpe.toFixed(2) : "—"} />
            <Stat label="Max DD" dim value={`${(cell.max_drawdown * 100).toFixed(1)}%`} />
            <Stat label="Trades" value={String(cell.trades)} />
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span className="quiet" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4 }}>Verdict</span>
              <VerdictBadge verdict={cell.verdict} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  big,
  dim,
  tone,
  tip,
}: {
  label: string;
  value: string;
  big?: boolean;
  dim?: boolean;
  tone?: "up" | "dn";
  tip?: string;
}) {
  const color = tone === "up" ? "var(--up)" : tone === "dn" ? "var(--down)" : dim ? "var(--ink-2, #8a8a8a)" : "var(--fg)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }} title={tip}>
      <span className="quiet" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</span>
      <span className="tab" style={{ fontSize: big ? 22 : 15, fontWeight: big ? 700 : 600, color }}>{value}</span>
    </div>
  );
}
