import { llmSpendOverviewSchema, type LlmSpendOverview } from "@cosmu/shared";
import { Activity, DollarSign, Flame, ReceiptText, RefreshCw } from "lucide-react";
import { AutoRefresh } from "../live-refresh";
import { LocalTime } from "../local-time";

export const dynamic = "force-dynamic";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:4000";

const money = (value: number | null | undefined, maximumFractionDigits = 2) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Unknown";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: maximumFractionDigits === 0 || value >= 100 ? 0 : 2,
    maximumFractionDigits
  });
};

const integer = new Intl.NumberFormat("en-US");

const getSpendOverview = async (): Promise<{ data: LlmSpendOverview | null; error: string | null }> => {
  const apiSecretKey = process.env.API_SECRET_KEY;
  if (!apiSecretKey) {
    return { data: null, error: "API_SECRET_KEY is required" };
  }

  try {
    const response = await fetch(`${apiBaseUrl}/spend/llm`, {
      cache: "no-store",
      signal: AbortSignal.timeout(25000),
      headers: { "x-api-key": apiSecretKey }
    });
    if (!response.ok) {
      throw new Error(`Spend request failed: ${response.status}`);
    }
    return { data: llmSpendOverviewSchema.parse(await response.json()), error: null };
  } catch (error) {
    return { data: null, error: error instanceof Error ? error.message : "Spend request failed" };
  }
};

export default async function SpendingPage() {
  const { data, error } = await getSpendOverview();

  if (!data) {
    return (
      <main className="page page-wide">
        <section className="command-hero">
          <div>
            <p className="eyebrow">Spending</p>
            <h1>API spend</h1>
          </div>
        </section>
        <section className="panel dashboard-error-state">
          <strong>Spend backend unavailable</strong>
          <code>{error}</code>
        </section>
      </main>
    );
  }

  const activeBurn = data.estimate.estimatedHourlyUsd;
  const topActive = [...data.estimate.bots]
    .sort((a, b) => (b.estimatedHourlyUsd ?? -1) - (a.estimatedHourlyUsd ?? -1))
    .slice(0, 8);

  return (
    <main className="page page-wide">
      <AutoRefresh intervalMs={60000} />
      <section className="command-hero">
        <div>
          <p className="eyebrow">Spending</p>
          <h1>API spend</h1>
          <p>Observed model costs, active burn rate, and recent run cost history.</p>
        </div>
        <div className="hero-actions command-actions">
          <span className="badge badge-neutral">Updated <LocalTime value={data.generatedAt} /></span>
          <a className="btn btn-secondary" href="/spending">
            <RefreshCw size={16} />
            Refresh
          </a>
        </div>
      </section>

      <section className="metric-strip">
        <article>
          <span>All-time observed</span>
          <strong>{money(data.totals.allTimeUsd, 2)}</strong>
          <small>{integer.format(data.totals.callCount)} model calls</small>
        </article>
        <article className="metric-card-emphasis">
          <span>Active burn</span>
          <strong>{money(activeBurn, 2)}/h</strong>
          <small>{data.estimate.activeBotCount} active agents</small>
        </article>
        <article>
          <span>Daily pace</span>
          <strong>{money(data.estimate.estimatedDailyUsd, 0)}</strong>
          <small>from recent per-agent averages</small>
        </article>
        <article>
          <span>Last 24h</span>
          <strong>{money(data.totals.last24hUsd, 2)}</strong>
          <small>known pricing subtotal</small>
        </article>
        <article>
          <span>Last 7d</span>
          <strong>{money(data.totals.last7dUsd, 2)}</strong>
          <small>{money(data.totals.last30dUsd, 2)} in 30d</small>
        </article>
        <article>
          <span>Unknown calls</span>
          <strong className={data.totals.unknownCostCallCount > 0 ? "value-red" : ""}>{data.totals.unknownCostCallCount}</strong>
          <small>missing pricing matches</small>
        </article>
      </section>

      <section className="spending-grid">
        <article className="panel">
          <div className="panel-table-header">
            <div>
              <p className="eyebrow">Live estimate</p>
              <h3>Highest active burn</h3>
            </div>
            <Flame size={18} />
          </div>
          <div className="data-table-scroll data-table-scroll-expanded">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Frequency</th>
                  <th>Per run</th>
                  <th>Hourly</th>
                </tr>
              </thead>
              <tbody>
                {topActive.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">No active agents are currently scheduled.</td>
                  </tr>
                ) : (
                  topActive.map((bot) => (
                    <tr key={bot.botId}>
                      <td>#{bot.botNumber} {bot.name}</td>
                      <td>{bot.frequencyMinutes}m</td>
                      <td>{money(bot.estimatedCostPerRunUsd, 4)}</td>
                      <td>{money(bot.estimatedHourlyUsd, 2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel">
          <div className="panel-table-header">
            <div>
              <p className="eyebrow">Observed</p>
              <h3>Top spenders</h3>
            </div>
            <DollarSign size={18} />
          </div>
          <div className="data-table-scroll data-table-scroll-expanded">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Total</th>
                  <th>24h</th>
                  <th>Calls</th>
                </tr>
              </thead>
              <tbody>
                {data.topBots.map((bot) => (
                  <tr key={bot.botId}>
                    <td>#{bot.botNumber} {bot.name}</td>
                    <td><span className={`badge ${bot.enabled ? "badge-success" : "badge-neutral"}`}>{bot.enabled ? "Active" : "Stopped"}</span></td>
                    <td>{money(bot.totalUsd, 2)}</td>
                    <td>{money(bot.last24hUsd, 2)}</td>
                    <td>{integer.format(bot.callCount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="spending-grid">
        <article className="panel">
          <div className="panel-table-header">
            <div>
              <p className="eyebrow">Recent</p>
              <h3>Run costs</h3>
            </div>
            <ReceiptText size={18} />
          </div>
          <div className="data-table-scroll data-table-scroll-expanded">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Agent</th>
                  <th>Status</th>
                  <th>Cost</th>
                  <th>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {data.recentRuns.map((run) => (
                  <tr key={run.runId}>
                    <td className="mono-badge">{run.runId.slice(0, 8)}</td>
                    <td>#{run.botNumber} {run.botName}</td>
                    <td><span className="badge badge-neutral">{run.status}</span></td>
                    <td>{money(run.totalUsd, 4)}</td>
                    <td>{integer.format(run.inputTokens + run.outputTokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel spending-source-panel">
          <div className="panel-table-header">
            <div>
              <p className="eyebrow">Rates</p>
              <h3>Pricing assumptions</h3>
              <p className="field-help">Source: {data.pricing.source} · <LocalTime value={data.pricing.updatedAt} /></p>
            </div>
            <Activity size={18} />
          </div>
          <div className="spend-bot-list">
            {data.pricing.assumptions.slice(0, 10).map((assumption) => (
              <div className="spend-bot-row" key={`${assumption.provider}:${assumption.model}`}>
                <div>
                  <strong>{assumption.provider} {assumption.model}</strong>
                  <small>{assumption.sourceUrl}</small>
                </div>
                <div className="spend-bot-cost">
                  <strong>{money(assumption.inputUsdPerMillion, 4)} / {money(assumption.outputUsdPerMillion, 4)}</strong>
                  <small>per 1M input/output tokens</small>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}
