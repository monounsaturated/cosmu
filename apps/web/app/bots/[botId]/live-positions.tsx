"use client";

import { useEffect, useState } from "react";

type Position = {
  id: string;
  symbol: string;
  quantity: number;
  avgEntryPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  safetyStopPrice: number | null;
  openedAt: string;
  currentPrice: number | null;
  pnlPct: number | null;
  unrealizedPnlUsd: number | null;
};

const fmtUsd = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  return v >= 0 ? `+$${v.toFixed(2)}` : `-$${Math.abs(v).toFixed(2)}`;
};

const fmtPct = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
};

export function LivePositions({ botId }: { botId: string }) {
  const [positions, setPositions] = useState<Position[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch(`/api/bots/${botId}/positions`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setPositions(data.positions ?? []);
      } catch {
        /* ignore transient errors */
      }
    };

    load();
    const timer = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [botId]);

  if (!positions || positions.length === 0) return null;

  return (
    <div className="grid" style={{ display: "block", marginBottom: "32px" }}>
      <div className="panel">
        <h3>Open Positions</h3>
        <p className="muted" style={{ marginBottom: "16px" }}>
          Live prices refresh every 5s. SL/TP fire via the app guardian; safety stop is a wider Binance STOP_LOSS that triggers only if the app is down.
        </p>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Current</th>
              <th>P&amp;L %</th>
              <th>P&amp;L USD</th>
              <th>SL</th>
              <th>TP</th>
              <th>Safety Stop</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const pnlColor =
                p.pnlPct === null ? undefined : p.pnlPct >= 0 ? "#22c55e" : "#ef4444";
              return (
                <tr key={p.id}>
                  <td>{p.symbol}</td>
                  <td>{p.quantity}</td>
                  <td>${p.avgEntryPrice}</td>
                  <td>{p.currentPrice !== null ? `$${p.currentPrice}` : "—"}</td>
                  <td style={{ color: pnlColor, fontWeight: 600 }}>{fmtPct(p.pnlPct)}</td>
                  <td style={{ color: pnlColor }}>{fmtUsd(p.unrealizedPnlUsd)}</td>
                  <td>${p.stopLossPrice}</td>
                  <td>${p.takeProfitPrice}</td>
                  <td>{p.safetyStopPrice !== null ? `$${p.safetyStopPrice}` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
