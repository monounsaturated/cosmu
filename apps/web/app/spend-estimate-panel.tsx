import type { DashboardPayload } from "@cosmu/shared";
import { Activity, AlertTriangle, DollarSign, Zap } from "lucide-react";

type SpendEstimatePanelProps = {
  estimate: DashboardPayload["llmSpendEstimate"];
};

const money = (value: number | null | undefined, maximumFractionDigits = 2) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Unknown";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: maximumFractionDigits === 0 || value >= 100 ? 0 : 2,
    maximumFractionDigits
  });
};

const numberFormat = new Intl.NumberFormat("en-US");

export function SpendEstimatePanel({ estimate }: SpendEstimatePanelProps) {
  if (!estimate) return null;

  const topBots = [...estimate.bots]
    .sort((a, b) => (b.estimatedHourlyUsd ?? -1) - (a.estimatedHourlyUsd ?? -1))
    .slice(0, 5);

  return (
    <section className="panel spend-panel" aria-label="Active LLM spend estimate">
      <div className="spend-panel-header">
        <div>
          <p className="eyebrow">API spend guard</p>
          <h3>Active model burn rate</h3>
          <p className="field-help">
            Based on token logs from the last {estimate.sampleWindowRuns} completed run{estimate.sampleWindowRuns === 1 ? "" : "s"} per active agent.
          </p>
        </div>
        <span className={estimate.unknownBotCount > 0 ? "badge badge-warn" : "badge badge-neutral"}>
          {estimate.activeBotCount} active
        </span>
      </div>

      <div className="spend-kpis">
        <div>
          <DollarSign size={17} />
          <span>Hourly</span>
          <strong>{money(estimate.estimatedHourlyUsd, 2)}</strong>
        </div>
        <div>
          <Zap size={17} />
          <span>Daily</span>
          <strong>{money(estimate.estimatedDailyUsd, 0)}</strong>
        </div>
        <div>
          <Activity size={17} />
          <span>Monthly pace</span>
          <strong>{money(estimate.estimatedMonthlyUsd, 0)}</strong>
        </div>
        <div className={estimate.unknownBotCount > 0 ? "spend-warning-kpi" : ""}>
          <AlertTriangle size={17} />
          <span>Unknown</span>
          <strong>{estimate.unknownBotCount}</strong>
        </div>
      </div>

      <div className="spend-bot-list">
        {topBots.length === 0 ? (
          <p className="muted">No active agents are currently generating scheduled model calls.</p>
        ) : (
          topBots.map((bot) => (
            <div className="spend-bot-row" key={bot.botId}>
              <div>
                <strong>Bot #{bot.botNumber}{bot.name?.trim() ? ` - ${bot.name}` : ""}</strong>
                <small>
                  Every {bot.frequencyMinutes}m · {bot.sampleRunCount} sample run{bot.sampleRunCount === 1 ? "" : "s"} ·{" "}
                  {numberFormat.format(bot.sampleInputTokens + bot.sampleOutputTokens)} tokens
                </small>
              </div>
              <div className="spend-bot-cost">
                <strong>{money(bot.estimatedHourlyUsd, 2)}/h</strong>
                <small>{bot.warning ?? `${money(bot.estimatedCostPerRunUsd, 4)} per run`}</small>
              </div>
            </div>
          ))
        )}
      </div>

      <p className="spend-note">
        {estimate.note}
      </p>
    </section>
  );
}
