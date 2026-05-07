import Link from "next/link";
import { notFound } from "next/navigation";
import { PerformanceChart } from "../../performance-chart";
import { BotControls } from "../../bot-controls";
import { AutoRefresh } from "../../live-refresh";
import { LocalTime } from "../../local-time";
import { LivePositions } from "./live-positions";
import { RecentRuns } from "./recent-runs";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";
export const dynamic = "force-dynamic";

function SettingPill({ label, on, extra }: { label: string; on: boolean; extra?: string }) {
  return (
    <span
      className={`badge ${on ? "badge-success" : "badge-inactive"}`}
      style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "12px" }}
    >
      <span style={{ fontSize: "10px" }}>{on ? "●" : "○"}</span>
      {label}{extra ? ` (${extra})` : ""}
    </span>
  );
}

async function fetchApi(path: string) {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) throw new Error("API_SECRET_KEY is required");

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      headers: { "x-api-key": apiSecretKey }
    });

    if (response.status === 404) return null;
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export default async function BotPage({ params }: { params: Promise<{ botId: string }> }) {
  const { botId } = await params;

  const [setup, details, runsResponse, dashboard] = await Promise.all([
    fetchApi(`/bots/${botId}/setup`),
    fetchApi(`/bots/${botId}/details`),
    fetchApi(`/bots/${botId}/runs?limit=20&offset=0`),
    fetchApi(`/dashboard`)
  ]);

  if (!setup) return notFound();

  const botNameDisplay = setup.name?.trim()
    ? `Bot #${setup.botNumber} — ${setup.name.trim()}`
    : `Bot #${setup.botNumber}`;
  const dashboardBot = dashboard?.bots?.find((b: any) => b.id === botId);
  const botSnapshot = dashboard?.latestSnapshots?.find((s: any) => s.botId === botId);
  const botSeries = dashboard?.performanceSeries?.filter((series: any) => series.botId === botId) ?? [];
  const netPnl = dashboardBot?.netPnlUsd ?? 0;
  const netPnlPct = setup.runtimeConfig.budgetUsdt > 0 ? (netPnl / setup.runtimeConfig.budgetUsdt) * 100 : 0;

  return (
    <main className="page">
      <div className="hero" style={{ paddingBottom: 0, marginBottom: "24px" }}>
        <div>
          <Link href="/" className="muted hover:opacity-80 transition-opacity" style={{ display: "inline-block", marginBottom: "16px", textDecoration: "none" }}>
            ← Back to Dashboard
          </Link>
          <h1>
            Bot #{setup.botNumber}
            {setup.name ? ` - ${setup.name}` : ""}
          </h1>
          <p className="muted">Detailed view of strategy, trades, and execution logs.</p>
        </div>
        <div style={{ display: "flex", alignItems: "flex-start" }}>
          <BotControls botId={botId} isActive={setup.runtimeConfig.enabled} />
        </div>
      </div>
      <AutoRefresh intervalMs={60000} />
      <LivePositions botId={botId} />

      <div className="grid" style={{ marginBottom: "24px", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <div className="panel">
          <p className="label">Status</p>
          <h2 style={{ margin: "4px 0", color: setup.runtimeConfig.enabled ? undefined : "#ef4444" }}>
            <span className={`status-dot ${setup.runtimeConfig.enabled ? "status-active" : "status-inactive"}`} style={{ display: "inline-block", marginRight: "6px" }} />
            {setup.runtimeConfig.enabled ? "Active" : "Killed"}
          </h2>
        </div>
        <div className="panel">
          <p className="label">Venue & Mode</p>
          <h2 style={{ margin: "4px 0" }}>{setup.runtimeConfig.venue} ({setup.runtimeConfig.mode})</h2>
        </div>
        <div className="panel">
          <p className="label">Frequency</p>
          <h2 style={{ margin: "4px 0" }}>Every {setup.runtimeConfig.frequencyMinutes}m</h2>
        </div>
        <div className="panel">
          <p className="label">Allocated Budget</p>
          <h2 style={{ margin: "4px 0" }}>${setup.runtimeConfig.budgetUsdt}</h2>
        </div>
        <div className="panel">
          <p className="label">Days Since Launch</p>
          <h2 style={{ margin: "4px 0" }}>{dashboardBot?.daysRunning?.toFixed(1) ?? "0.0"}</h2>
        </div>
      </div>

      <div className="grid" style={{ display: 'block', marginBottom: '32px' }}>
        <div className="panel">
          <h3>Performance & Current Holdings</h3>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "16px", marginTop: "16px", marginBottom: "24px" }}>
            <div>
              <p className="label">Current Portfolio USD</p>
              <h2>${dashboardBot?.currentPortfolioUsd?.toFixed(2) ?? setup.runtimeConfig.budgetUsdt.toFixed(2)}</h2>
            </div>
            <div>
              <p className="label">Net PnL</p>
              <h2 className={dashboardBot?.netPnlUsd && dashboardBot.netPnlUsd > 0 ? "value-green" : dashboardBot?.netPnlUsd && dashboardBot.netPnlUsd < 0 ? "value-red" : ""}>
                {dashboardBot?.netPnlUsd && dashboardBot.netPnlUsd > 0 ? "+" : ""}{dashboardBot?.netPnlUsd?.toFixed(2) ?? "0.00"}
              </h2>
            </div>
            <div>
              <p className="label">Net Return</p>
              <h2 className={netPnl > 0 ? "value-green" : netPnl < 0 ? "value-red" : ""}>
                {netPnl > 0 ? "+" : ""}{netPnlPct.toFixed(2)}%
              </h2>
            </div>
            <div>
              <p className="label">Total Trades</p>
              <h2>{dashboardBot?.tradeCount ?? 0}</h2>
            </div>
            <div>
              <p className="label">Fees Paid</p>
              <h2>${dashboardBot?.totalFeesUsd?.toFixed(2) ?? "0.00"}</h2>
            </div>
          </div>

          <h4>Holdings</h4>
          {botSnapshot && botSnapshot.snapshot.balances.length > 0 ? (
            <ul style={{ marginTop: "16px", paddingLeft: "20px", fontSize: "14px" }}>
              {botSnapshot.snapshot.balances.map((b: any) => (
                <li key={b.asset} style={{ marginBottom: "8px" }}>
                  <strong>{b.asset}</strong>: {(b.free + b.locked).toFixed(8)} 
                  <span className="muted" style={{ marginLeft: "8px" }}>(${b.usdValue?.toFixed(2) ?? "0.00"})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ marginTop: "16px" }}>No holdings recorded yet.</p>
          )}
        </div>
      </div>

      <div className="grid" style={{ display: "block", marginBottom: "32px" }}>
        <div className="panel">
          <h3>Bot Value Evolution</h3>
          <PerformanceChart series={botSeries} />
        </div>
      </div>

      <div className="grid" style={{ display: 'block', marginBottom: '32px' }}>
        <div className="panel">
          <h3>Bot Settings</h3>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "24px", marginTop: "16px" }}>
            <div>
              <p className="label">Research Prompt</p>
              <p><span className="badge badge-neutral">{setup.promptVersionLabel}</span></p>
            </div>
            <div>
              <p className="label">Trader Prompt</p>
              <p><span className="badge badge-neutral">{setup.traderPromptVersionLabel ?? "Default"}</span></p>
            </div>
            <div>
              <p className="label">Research Model</p>
              <p>{setup.modelProfileName} <span className="muted">({setup.modelProvider} / {setup.modelIdentifier})</span></p>
            </div>
            <div>
              <p className="label">Trader Model</p>
              <p>{setup.traderModelProfileName ?? setup.modelProfileName} <span className="muted">({setup.traderModelProvider ?? setup.modelProvider} / {setup.traderModelIdentifier ?? setup.modelIdentifier})</span></p>
            </div>
          </div>

          <div style={{ marginTop: "24px" }}>
            <p className="label" style={{ marginBottom: "12px" }}>Injected Data Modules</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              <SettingPill label="Current Positions" on={!!setup.promptConfig?.modules?.includeCurrentPositions} />
              <SettingPill label="Past Trades" on={!!setup.promptConfig?.modules?.includePastTrades} extra={setup.promptConfig?.modules?.includePastTrades ? `last ${setup.promptConfig.modules.pastTradesLookback}` : undefined} />
              <SettingPill label="Performance Stats" on={!!setup.promptConfig?.modules?.includePerformanceStats} />
              <SettingPill label="Bot Ranking" on={!!setup.promptConfig?.modules?.includeBotRanking} />
              <SettingPill label="Wallet Overview" on={!!setup.promptConfig?.modules?.includeWalletOverview} />
              <SettingPill label="Loop Prompt" on={!!setup.promptConfig?.extraLoopPrompt?.trim()} />
            </div>
          </div>

          <div style={{ marginTop: "24px" }}>
            <p className="label" style={{ marginBottom: "12px" }}>Execution Rules</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              <SettingPill label="Live Execution" on={setup.runtimeConfig.execution.enabled} />
              <SettingPill label="Market Orders" on={setup.runtimeConfig.execution.allowMarketOrders} />
              <SettingPill label="Limit Orders" on={setup.runtimeConfig.execution.allowLimitOrders} />
            </div>
            {setup.runtimeConfig.execution.enabled && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "16px", marginTop: "12px" }}>
                <div>
                  <p className="label">Max Orders / Run</p>
                  <p>{setup.runtimeConfig.execution.maxOrdersPerRun}</p>
                </div>
                <div>
                  <p className="label">Max Notional / Order</p>
                  <p>${setup.runtimeConfig.execution.maxNotionalPerOrderUsd}</p>
                </div>
                <div>
                  <p className="label">Min Cash Reserve</p>
                  <p>${setup.runtimeConfig.execution.minCashReserveUsd}</p>
                </div>
              </div>
            )}
          </div>

          <div style={{ marginTop: "24px" }}>
            <p className="label" style={{ marginBottom: "8px" }}>Trading Pairs</p>
            {setup.runtimeConfig.symbolScope === "all" ? (
              <span className="badge badge-neutral">All Pairs</span>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {setup.runtimeConfig.contextSymbols.map((s: string) => (
                  <span key={s} className="badge badge-neutral" style={{ fontSize: "12px" }}>{s}</span>
                ))}
              </div>
            )}
          </div>

          <div style={{ marginTop: "24px" }} id="prompt">
            <p className="label">Research Prompt</p>
            <div className="run-detail-pre" style={{ maxHeight: "400px", overflowY: "auto", borderLeft: "3px solid #60a5fa" }}>
              {setup.promptBody?.trim() ? setup.promptBody : <span className="muted">No research prompt body on this prompt version.</span>}
            </div>
          </div>

          <div style={{ marginTop: "16px" }}>
            <p className="label">Trader Prompt</p>
            <div className="run-detail-pre" style={{ maxHeight: "400px", overflowY: "auto", borderLeft: "3px solid #a78bfa" }}>
              {setup.traderPromptBody?.trim() ? setup.traderPromptBody : <span className="muted">Using default trader prompt.</span>}
            </div>
          </div>
        </div>
      </div>

      {details && details.pastTrades && details.pastTrades.length > 0 && (
        <div className="grid" style={{ display: 'block', marginBottom: '32px' }}>
          <div className="panel">
            <h3>Recent Trades</h3>
            <table className="table" style={{ marginTop: "16px" }}>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Quantity</th>
                  <th>Avg Price</th>
                  <th>Notional USD</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                {details.pastTrades.map((trade: any) => (
                  <tr key={`${trade.createdAt}-${trade.symbol}`}>
                    <td><LocalTime value={trade.createdAt} /></td>
                    <td>{trade.symbol}</td>
                    <td><span className={`badge badge-${trade.side}`}>{trade.side}</span></td>
                    <td>{trade.orderType}</td>
                    <td><span className={`badge badge-${trade.status}`}>{trade.status}</span></td>
                    <td>{trade.executedQuantity}</td>
                    <td>{trade.averageFillPrice ? `$${trade.averageFillPrice}` : "—"}</td>
                    <td>{trade.executedNotionalUsd ? `$${trade.executedNotionalUsd}` : "—"}</td>
                    <td>{trade.stopLossPrice ? `$${trade.stopLossPrice}` : "—"}</td>
                    <td>{trade.takeProfitPrice ? `$${trade.takeProfitPrice}` : "—"}</td>
                    <td>
                      <span className={`badge ${trade.isActive ? "badge-running" : "badge-neutral"}`}>
                        {trade.isActive ? "Active" : "Closed"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid" style={{ display: 'block', marginBottom: '32px' }}>
        <div className="panel">
          <h3>Recent Execution Runs</h3>
          <p className="muted" style={{ marginBottom: "16px" }}>Click to expand for full input/output logs. Guardian (SL/TP) runs are hidden by default.</p>
          <RecentRuns botId={botId} initialData={runsResponse} />
        </div>
      </div>

    </main>
  );
}
