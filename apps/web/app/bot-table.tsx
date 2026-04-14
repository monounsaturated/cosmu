"use client";

import { Fragment, useState } from "react";
import type { DashboardPayload, BotSummary } from "@cosmu/shared";
import { BotControls } from "./bot-controls";

import Link from "next/link";

type SortField = "botNumber" | "startedAt" | "netPnlUsd" | "runCount" | "tradeCount" | "currentPortfolioUsd";
type SortOrder = "asc" | "desc";

export function BotTable({ dashboard }: { dashboard: DashboardPayload }) {
  const [sortField, setSortField] = useState<SortField>("botNumber");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [expandedBotId, setExpandedBotId] = useState<string | null>(null);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortOrder("desc"); // Default to desc when switching to a new metric like PnL
    }
  };

  const sortedBots = [...dashboard.bots].sort((a, b) => {
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
    if (sortField !== field) return <span style={{ opacity: 0.3 }}>↕</span>;
    return <span>{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  return (
    <div className="panel" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th className="clickable" onClick={() => handleSort("botNumber")}>
              Bot <SortIndicator field="botNumber" />
            </th>
            <th>Status</th>
            <th className="clickable" onClick={() => handleSort("startedAt")}>
              Created <SortIndicator field="startedAt" />
            </th>
            <th>Strategy</th>
            <th className="clickable text-right" onClick={() => handleSort("currentPortfolioUsd")}>
              Portfolio <SortIndicator field="currentPortfolioUsd" />
            </th>
            <th className="clickable text-right" onClick={() => handleSort("netPnlUsd")}>
              Net PnL <SortIndicator field="netPnlUsd" />
            </th>
            <th className="clickable text-right" onClick={() => handleSort("tradeCount")}>
              Trades <SortIndicator field="tradeCount" />
            </th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sortedBots.map((bot) => {
            const isExpanded = expandedBotId === bot.id;
            const botNameDisplay = bot.name ? `Bot #${bot.botNumber} - ${bot.name}` : `Bot #${bot.botNumber}`;
            
            // Get bot specific data from dashboard
            const botRuns = dashboard.recentRuns.filter(r => r.botName === botNameDisplay);
            const botSnapshots = dashboard.latestSnapshots.find(s => s.botName === botNameDisplay);

            return (
              <Fragment key={bot.id}>
                <tr className={`run-row ${isExpanded ? "run-row-expanded" : ""}`} onClick={() => setExpandedBotId(isExpanded ? null : bot.id)}>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="run-expand-icon">{isExpanded ? "▼" : "▶"}</span>
                      <Link href={`/bots/${bot.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                        <strong>#{bot.botNumber}</strong> {bot.name}
                      </Link>
                    </div>
                  </td>
                  <td>
                    <span className={`status-dot ${bot.enabled ? "status-active" : "status-inactive"}`} style={{ display: "inline-block", marginRight: "6px" }} />
                    {bot.enabled ? "Active" : "Paused"}
                  </td>
                  <td>{new Date(bot.startedAt).toLocaleDateString()}</td>
                  <td>
                    <div style={{ fontSize: "12px" }}>
                      <Link href={`/bots/${bot.id}#prompt`} style={{ textDecoration: 'none', color: 'inherit' }} onClick={(e) => e.stopPropagation()}>
                        <span className="badge badge-neutral hover:opacity-80 transition-opacity">{bot.promptVersionLabel}</span>
                      </Link>
                      <br/>
                      <span className="muted" style={{ fontSize: "11px", marginTop: "4px", display: "inline-block" }}>{bot.modelProfileName}</span>
                    </div>
                  </td>
                  <td className="text-right">
                    {bot.currentPortfolioUsd !== null ? `$${bot.currentPortfolioUsd.toFixed(2)}` : "—"}
                  </td>
                  <td className="text-right">
                    {bot.netPnlUsd !== null ? (
                      <div className={bot.netPnlUsd > 0 ? "value-green" : bot.netPnlUsd < 0 ? "value-red" : ""}>
                        {bot.netPnlUsd > 0 ? "+" : ""}${bot.netPnlUsd.toFixed(2)}
                        <br/>
                        <span style={{ fontSize: "11px", opacity: 0.8 }}>
                          {bot.netPnlUsd > 0 ? "+" : ""}{((bot.netPnlUsd / bot.budgetUsdt) * 100).toFixed(2)}%
                        </span>
                      </div>
                    ) : "—"}
                  </td>
                  <td className="text-right">{bot.tradeCount}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <BotControls botId={bot.id} enabled={bot.enabled} />
                  </td>
                </tr>

                {isExpanded && (
                  <tr className="run-detail-row">
                    <td colSpan={8}>
                      <div className="run-detail-panels" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
                        
                        <div className="run-detail-panel">
                          <h4>Bot Details</h4>
                          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                            <div>
                              <span className="label">Venue</span>
                              <div>{bot.venue} ({bot.mode})</div>
                            </div>
                            <div>
                              <span className="label">Budget</span>
                              <div>${bot.budgetUsdt}</div>
                            </div>
                            <div>
                              <span className="label">Frequency</span>
                              <div>{bot.frequencyMinutes}m</div>
                            </div>
                            <div>
                              <span className="label">Days Live</span>
                              <div>{bot.daysRunning.toFixed(1)}</div>
                            </div>
                            <div>
                              <span className="label">Gross PnL</span>
                              <div className={bot.grossPnlUsd && bot.grossPnlUsd > 0 ? "value-green" : bot.grossPnlUsd && bot.grossPnlUsd < 0 ? "value-red" : ""}>
                                {bot.grossPnlUsd !== null ? `$${bot.grossPnlUsd.toFixed(2)}` : "—"}
                              </div>
                            </div>
                            <div>
                              <span className="label">Fees Paid</span>
                              <div>{bot.totalFeesUsd !== null ? `$${bot.totalFeesUsd.toFixed(2)}` : "—"}</div>
                            </div>
                          </div>

                          <h4>Latest Decision</h4>
                          <div className="run-detail-pre">
                            {bot.latestDecisionSummary || "No runs yet"}
                          </div>
                          {bot.latestError && (
                            <div className="form-error" style={{ marginTop: "8px" }}>
                              {bot.latestError}
                            </div>
                          )}
                        </div>

                        <div className="run-detail-panel">
                          <h4>Recent Runs for this Bot</h4>
                          {botRuns.length > 0 ? (
                            <table className="table" style={{ fontSize: "12px" }}>
                              <thead>
                                <tr>
                                  <th>Time</th>
                                  <th>Status</th>
                                  <th>Mode</th>
                                </tr>
                              </thead>
                              <tbody>
                                {botRuns.slice(0, 5).map(r => (
                                  <tr key={r.id}>
                                    <td>{new Date(r.startedAt).toLocaleString()}</td>
                                    <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                                    <td>{r.decisionMode || "—"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ) : (
                            <p className="muted">No recent runs.</p>
                          )}

                          <h4 style={{ marginTop: "16px" }}>Current Holdings</h4>
                          {botSnapshots ? (
                            <ul style={{ margin: 0, paddingLeft: "16px", color: "#e4e4e7", fontSize: "13px" }}>
                              {botSnapshots.snapshot.balances.map((balance) => (
                                <li key={balance.asset}>
                                  <strong>{balance.asset}</strong>: {(balance.free + balance.locked).toFixed(6)}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="muted">No snapshot available.</p>
                          )}
                        </div>

                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {sortedBots.length === 0 && <p className="muted" style={{ padding: "20px", textAlign: "center" }}>No bots created yet.</p>}
    </div>
  );
}