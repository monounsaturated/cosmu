"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { DashboardPayload } from "@cosmu/shared";
import { BotControls } from "./bot-controls";

type SortField = "botNumber" | "startedAt" | "netPnlUsd" | "tradeCount" | "currentPortfolioUsd";
type SortOrder = "asc" | "desc";

const venueLabel = (venue: "binance" | "binance-testnet") =>
  venue === "binance-testnet" ? "Binance Testnet" : "Binance";

export function BotTable({ dashboard }: { dashboard: DashboardPayload }) {
  const router = useRouter();
  const [sortField, setSortField] = useState<SortField>("botNumber");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((value) => (value === "asc" ? "desc" : "asc"));
      return;
    }

    setSortField(field);
    setSortOrder(field === "botNumber" || field === "startedAt" ? "asc" : "desc");
  };

  const sortedBots = [...dashboard.bots].sort((a, b) => {
    if (a.enabled !== b.enabled) {
      return a.enabled ? -1 : 1;
    }

    const aValue = a[sortField];
    const bValue = b[sortField];
    if (aValue === null && bValue !== null) return sortOrder === "asc" ? -1 : 1;
    if (aValue !== null && bValue === null) return sortOrder === "asc" ? 1 : -1;
    if (aValue === null && bValue === null) return 0;
    if (aValue! < bValue!) return sortOrder === "asc" ? -1 : 1;
    if (aValue! > bValue!) return sortOrder === "asc" ? 1 : -1;
    return 0;
  });

  const SortIndicator = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span style={{ opacity: 0.25 }}>↕</span>;
    return <span>{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  return (
    <div className="panel" style={{ overflowX: "auto" }}>
      <table className="table table-compact">
        <thead>
          <tr>
            <th className="clickable" onClick={() => handleSort("botNumber")}>
              Bot <SortIndicator field="botNumber" />
            </th>
            <th>Status</th>
            <th>Venue</th>
            <th className="clickable" onClick={() => handleSort("startedAt")}>
              Created <SortIndicator field="startedAt" />
            </th>
            <th>Prompt</th>
            <th className="clickable text-right" onClick={() => handleSort("currentPortfolioUsd")}>
              Value <SortIndicator field="currentPortfolioUsd" />
            </th>
            <th className="clickable text-right" onClick={() => handleSort("netPnlUsd")}>
              Net PnL <SortIndicator field="netPnlUsd" />
            </th>
            <th className="text-right">%</th>
            <th className="clickable text-right" onClick={() => handleSort("tradeCount")}>
              Trades <SortIndicator field="tradeCount" />
            </th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sortedBots.map((bot) => (
            <tr
              key={bot.id}
              className="run-row"
              onClick={() => router.push(`/bots/${bot.id}`)}
            >
              <td>
                <strong>#{bot.botNumber}</strong>
                {bot.name ? ` ${bot.name}` : ""}
              </td>
              <td>
                <span className={`status-dot ${bot.enabled ? "status-active" : "status-inactive"}`} style={{ display: "inline-block", marginRight: "6px" }} />
                {bot.enabled ? "Active" : "Paused"}
              </td>
              <td>{venueLabel(bot.venue)}</td>
              <td>{new Date(bot.startedAt).toLocaleDateString()}</td>
              <td>
                <div style={{ fontSize: "12px", lineHeight: 1.35 }}>
                  <span className="badge badge-neutral">{bot.promptVersionLabel}</span>
                  <div className="muted" style={{ fontSize: "11px" }}>{bot.modelProfileName}</div>
                </div>
              </td>
              <td className="text-right">
                {bot.currentPortfolioUsd !== null ? `$${bot.currentPortfolioUsd.toFixed(2)}` : "—"}
              </td>
              <td className="text-right">
                {bot.netPnlUsd !== null ? (
                  <span className={bot.netPnlUsd > 0 ? "value-green" : bot.netPnlUsd < 0 ? "value-red" : ""}>
                    {bot.netPnlUsd > 0 ? "+" : ""}${bot.netPnlUsd.toFixed(2)}
                  </span>
                ) : "—"}
              </td>
              <td className="text-right">
                {bot.netPnlUsd !== null ? (
                  <span className={bot.netPnlUsd > 0 ? "value-green" : bot.netPnlUsd < 0 ? "value-red" : ""}>
                    {bot.netPnlUsd > 0 ? "+" : ""}
                    {((bot.netPnlUsd / bot.budgetUsdt) * 100).toFixed(2)}%
                  </span>
                ) : "—"}
              </td>
              <td className="text-right">{bot.tradeCount}</td>
              <td onClick={(event) => event.stopPropagation()}>
                <BotControls botId={bot.id} enabled={bot.enabled} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sortedBots.length === 0 && <p className="muted" style={{ padding: "20px", textAlign: "center" }}>No bots created yet.</p>}
    </div>
  );
}