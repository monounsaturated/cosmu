"use client";

// module: CostBasisSelector — the fee-basis picker. Lets the operator see this strategy's net return under
// different cost bases (No fees / venue-1 / venue-2 / …) and pick which to view. It calls the engine's
// on-demand recompute GET /explorer/{id}/cost-basis (cost_basis.py → cost_surface, the pure backtest) — so
// every number is REAL, never fabricated; an honest "—" + reason renders when the engine can't recompute
// (offline / asset class not wired). Loaded lazily behind a button so the recompute only runs when asked.
// Styling is self-contained inline (theme-agnostic neutrals) + the existing .psec/.phase-tbl chrome.

import type { CSSProperties } from "react";
import { useState } from "react";
import type { CostBasisCell, CostBasisResponse } from "@cosmu/contracts-ts";
import { engineGetJson } from "@/lib/engine";
import { cn } from "@/lib/utils";

function pct(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

const btnStyle: CSSProperties = {
  fontSize: 12,
  padding: "6px 10px",
  borderRadius: 6,
  border: "1px solid rgba(255,255,255,0.14)",
  background: "transparent",
  color: "inherit",
  cursor: "pointer"
};

function tabStyle(on: boolean): CSSProperties {
  return {
    fontSize: 11,
    padding: "4px 9px",
    borderRadius: 5,
    cursor: "pointer",
    color: "inherit",
    border: on ? "1px solid rgba(255,255,255,0.45)" : "1px solid rgba(255,255,255,0.14)",
    background: on ? "rgba(255,255,255,0.08)" : "transparent",
    fontWeight: on ? 600 : 400
  };
}

export function CostBasisSelector({ versionId }: { versionId: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [data, setData] = useState<CostBasisResponse | null>(null);
  const [selected, setSelected] = useState<string>("none");

  async function load() {
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError(false);
    try {
      const res = await engineGetJson<CostBasisResponse>(`/explorer/${versionId}/cost-basis`);
      setData(res);
      const firstVenue = res.cells.find((c) => c.basis !== "none");
      setSelected(firstVenue ? firstVenue.basis : "none");
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <div className="psec">
        <div className="psec-title">Cost basis</div>
        <button type="button" style={btnStyle} onClick={load}>
          Compare fees across venues
        </button>
        <p className="quiet" style={{ fontSize: 11, marginTop: 6 }}>
          Recompute net return under No-fees and each venue&apos;s real fee + market depth — pick the basis to view.
        </p>
      </div>
    );
  }

  const cells: CostBasisCell[] = data?.cells ?? [];
  const cell = cells.find((c) => c.basis === selected) ?? cells[0] ?? null;

  return (
    <div className="psec">
      <div className="psec-title">Cost basis</div>

      {loading && <p className="quiet" style={{ fontSize: 11 }}>Computing across venues…</p>}
      {error && <p className="quiet" style={{ fontSize: 11 }}>— couldn&apos;t compute the cost basis right now.</p>}
      {data && !data.available && (
        <p className="quiet" style={{ fontSize: 11 }}>— {data.reason ?? "not available for this strategy"}.</p>
      )}

      {data?.available && cell && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {cells.map((c) => (
              <button key={c.basis} type="button" style={tabStyle(c.basis === selected)} onClick={() => setSelected(c.basis)}>
                {c.label}
              </button>
            ))}
          </div>

          <div style={{ marginBottom: 8 }}>
            <span className={cn(cell.net_return_pct >= 0 ? "up" : "dn")} style={{ fontSize: 22, fontWeight: 600 }}>
              {pct(cell.net_return_pct)}
            </span>
            <span className="quiet" style={{ fontSize: 11, marginLeft: 8 }}>
              net · {cell.fee_bps} bps fee · {cell.slippage_bps} bps slippage · {cell.num_trades} trades ·{" "}
              {cell.holds ? "edge holds" : "edge gone"}
            </span>
          </div>

          <div className="tbl-scroll">
            <table className="phase-tbl">
              <thead>
                <tr>
                  <th>Basis</th>
                  <th className="r">Fee</th>
                  <th className="r">Net</th>
                  <th className="r" data-tip="Share of the friction-free edge this basis keeps (100% = costs cost nothing).">
                    Keeps
                  </th>
                </tr>
              </thead>
              <tbody>
                {cells.map((c) => (
                  <tr key={c.basis} className={c.basis === selected ? "cur-ev" : ""}>
                    <td>{c.label}</td>
                    <td className="r tab">{c.fee_bps} bps</td>
                    <td className={cn("r tab", c.net_return_pct >= 0 ? "up" : "dn")}>{pct(c.net_return_pct)}</td>
                    <td className="r tab muted">{Math.round(c.cost_ratio * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="quiet" style={{ fontSize: 10, marginTop: 6 }}>
            Self-consistent re-screen on real cached bars — the relative ordering across venues is the signal.
          </p>
        </>
      )}
    </div>
  );
}
