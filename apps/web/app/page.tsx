import { ArrowUpRight, BadgeDollarSign, BrainCircuit, CircleDollarSign, Gauge, LockKeyhole, RadioTower, ShieldCheck } from "lucide-react";
import { ConsoleBox } from "./console-box";
import { getEvents, getLeaderboard, getPortfolio, getRecommendations, getStrategy } from "./data";
import type { Allocation, Backtest, CostSlice, Event, LeaderboardRow, Recommendation } from "@cosmu/contracts-ts";

function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function EquityChart({ points }: { points: { ts: string; value: number }[] }) {
  const width = 720;
  const height = 260;
  const min = Math.min(...points.map((point) => point.value));
  const max = Math.max(...points.map((point) => point.value));
  const span = Math.max(max - min, 1);
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.value - min) / span) * (height - 20) - 10;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Pooled wallet equity curve">
      <path d={path} fill="none" stroke="var(--green)" strokeWidth="3" />
      <path d={`${path} L ${width} ${height} L 0 ${height} Z`} fill="rgba(53,208,127,.08)" />
      <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="var(--line)" />
    </svg>
  );
}

export default async function HomePage() {
  const [portfolio, leaderboard, strategy, recommendations, events] = await Promise.all([
    getPortfolio(),
    getLeaderboard(),
    getStrategy("sv-btc"),
    getRecommendations(),
    getEvents()
  ]);
  const equity = portfolio.equity_curve.at(-1)?.value ?? 100000;
  const costsTotal = portfolio.costs.reduce((sum: number, item: CostSlice) => sum + item.amount, 0);

  return (
    <div className="page">
      <section className="surface" id="dashboard">
        <div className="eyebrow">deterministic master + autonomous lab</div>
        <h1>Autonomous strategy farming with the scorer and money out of the agent&apos;s reach.</h1>
        <div className="grid metrics" style={{ marginTop: 18 }}>
          <div className="card metric">
            <small>Pooled paper equity</small>
            <strong>{formatUsd(equity)}</strong>
            <span className="pill good"><ArrowUpRight size={14} /> {formatUsd(portfolio.pnl_net)} net</span>
          </div>
          <div className="card metric">
            <small>Opex vs alpha</small>
            <strong>{Math.round(portfolio.opex_vs_alpha * 100)}%</strong>
            <span className="subtle">auto-throttle below edge</span>
          </div>
          <div className="card metric">
            <small>Live gate</small>
            <strong>{portfolio.live_enabled ? "ON" : "OFF"}</strong>
            <span className="pill warn"><LockKeyhole size={14} /> approval required</span>
          </div>
          <div className="card metric">
            <small>Capital valve</small>
            <strong>4 gates</strong>
            <span className="subtle">WFO, holdout, paper, caps</span>
          </div>
        </div>
        <div className="grid two" style={{ marginTop: 12 }}>
          <div className="card">
            <div className="surface-header">
              <div>
                <h2>Pooled wallet</h2>
                <p className="subtle">Paper and live share one code path; this view shows money truth net of costs.</p>
              </div>
              <span className="pill good"><CircleDollarSign size={14} /> net of fees</span>
            </div>
            <EquityChart points={portfolio.equity_curve} />
          </div>
          <div className="card stack">
            <h2>Allocation and costs</h2>
            {portfolio.allocation.map((item: Allocation) => (
              <div className="row" key={item.strategy_id}>
                <div>
                  <strong>{item.name}</strong>
                  <div className="subtle">{item.venue}</div>
                </div>
                <div className="mono">{Math.round(item.weight * 100)}%</div>
              </div>
            ))}
            <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }} className="stack">
              {portfolio.costs.map((item: CostSlice) => (
                <div className="row" key={item.category}>
                  <span className="subtle">{item.category}</span>
                  <span className="mono">{formatUsd(item.amount)}</span>
                </div>
              ))}
              <div className="row">
                <strong>Total daily opex</strong>
                <strong>{formatUsd(costsTotal)}</strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="surface" id="leaderboard">
        <div className="surface-header">
          <div>
            <div className="eyebrow">leaderboard</div>
            <h2>Every version earns its own standardized sleeve.</h2>
          </div>
          <span className="pill"><Gauge size={14} /> ranked by deflated OOS Sharpe</span>
        </div>
        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Status</th>
                <th>Sleeve</th>
                <th>Net</th>
                <th>D Sharpe</th>
                <th>PBO</th>
                <th>Lineage</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.rows.map((row: LeaderboardRow) => (
                <tr key={row.version_id}>
                  <td><a href={`/strategy/${row.version_id}`}><strong>{row.name}</strong></a></td>
                  <td><span className={`pill ${row.status === "killed" ? "bad" : row.status === "paper" ? "good" : "warn"}`}>{row.status}</span></td>
                  <td className="mono">{formatPct(row.sleeve_return_pct)}</td>
                  <td className="mono">{formatPct(row.net_pct)}</td>
                  <td className="mono">{row.deflated_sharpe.toFixed(2)}</td>
                  <td className="mono">{row.pbo.toFixed(2)}</td>
                  <td className="subtle">{row.lineage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="surface" id="strategy">
        <div className="surface-header">
          <div>
            <div className="eyebrow">strategy detail</div>
            <h2>{strategy.name}</h2>
          </div>
          <span className="pill good"><ShieldCheck size={14} /> scorer-owned gates</span>
        </div>
        <div className="grid two">
          <div className="card stack">
            <h3>Evidence</h3>
            {strategy.backtests.map((backtest: Backtest) => (
              <div className="row" key={backtest.id}>
                <div>
                  <strong>{backtest.kind}</strong>
                  <div className="subtle">{backtest.num_trades} trades · max DD {(backtest.max_dd * 100).toFixed(1)}%</div>
                </div>
                <div className="mono">{backtest.deflated_sharpe.toFixed(2)} dS</div>
              </div>
            ))}
            <p className="subtle">{strategy.notes_md}</p>
          </div>
          <div className="card stack">
            <h3>Compiled artifact</h3>
            <pre className="code">{strategy.generated_code}</pre>
            <div className="row">
              <span className="subtle">Holdout</span>
              <span className="pill good">seen once · passed</span>
            </div>
          </div>
        </div>
      </section>

      <section className="surface" id="console">
        <div className="surface-header">
          <div>
            <div className="eyebrow">console</div>
            <h2>Chat, voice, images, recommendations.</h2>
          </div>
          <span className="pill"><BrainCircuit size={14} /> LLM proposes, master disposes</span>
        </div>
        <div className="console">
          <div className="card">
            <ConsoleBox />
          </div>
          <div className="stack">
            <div className="card stack">
              <h3>Recommendations</h3>
              {recommendations.map((item: Recommendation) => (
                <div className="stack" key={item.id} style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                  <span className="pill warn">{item.kind}</span>
                  <p>{item.body}</p>
                </div>
              ))}
            </div>
            <div className="card stack">
              <h3>Audit stream</h3>
              {events.map((event: Event) => (
                <div className="row" key={event.id}>
                  <div>
                    <strong>{event.kind}</strong>
                    <div className="subtle">{event.actor} · {event.ref_type ?? "system"}</div>
                  </div>
                  <RadioTower size={15} color="var(--cyan)" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
