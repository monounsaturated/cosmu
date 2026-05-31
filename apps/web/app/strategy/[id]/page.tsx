import { ArrowLeft, ShieldCheck } from "lucide-react";
import { getStrategy } from "../../data";
import type { Backtest, Execution } from "@cosmu/contracts-ts";

export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const strategy = await getStrategy(id);
  return (
    <div className="page">
      <section className="surface">
        <a href="/#leaderboard" className="pill">
          <ArrowLeft size={14} />
          Leaderboard
        </a>
        <div className="surface-header" style={{ marginTop: 18 }}>
          <div>
            <div className="eyebrow">strategy version</div>
            <h1>{strategy.name}</h1>
          </div>
          <span className="pill good"><ShieldCheck size={14} /> deterministic evidence</span>
        </div>
        <div className="grid two">
          <div className="card stack">
            <h2>Spec</h2>
            <pre className="code">{JSON.stringify(strategy.spec, null, 2)}</pre>
            <h2>Trades</h2>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Fee</th>
                    <th>Venue</th>
                  </tr>
                </thead>
                <tbody>
                  {strategy.trades.map((trade: Execution) => (
                    <tr key={trade.id}>
                      <td>{trade.side}</td>
                      <td className="mono">{trade.qty}</td>
                      <td className="mono">{trade.price}</td>
                      <td className="mono">{trade.fee}</td>
                      <td>{trade.venue}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="card stack">
            <h2>Gate history</h2>
            {strategy.backtests.map((backtest: Backtest) => (
              <div className="card" key={backtest.id}>
                <div className="row">
                  <strong>{backtest.kind}</strong>
                  <span className={backtest.passed_gates ? "pill good" : "pill bad"}>{backtest.passed_gates ? "passed" : "blocked"}</span>
                </div>
                <div className="row">
                  <span className="subtle">deflated Sharpe</span>
                  <span className="mono">{backtest.deflated_sharpe.toFixed(2)}</span>
                </div>
                <div className="row">
                  <span className="subtle">PBO</span>
                  <span className="mono">{backtest.pbo.toFixed(2)}</span>
                </div>
              </div>
            ))}
            <h2>Compiled code</h2>
            <pre className="code">{strategy.generated_code}</pre>
          </div>
        </div>
      </section>
    </div>
  );
}
