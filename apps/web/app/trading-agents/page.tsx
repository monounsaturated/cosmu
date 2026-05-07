"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, TrendingUp, TrendingDown, Minus, Clock, AlertCircle, ChevronDown, ChevronRight } from "lucide-react";

type AnalysisResult = {
  ticker: string;
  date: string;
  decision: string;
  market_report?: string;
  sentiment_report?: string;
  news_report?: string;
  fundamentals_report?: string;
  investment_plan?: string;
  trader_decision?: string;
  final_decision?: string;
  status: string;
};

type HistoryItem = {
  request_id: string;
  ticker: string;
  date: string;
  decision: string;
  status: string;
};

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "xai", label: "xAI" },
  { value: "deepseek", label: "DeepSeek" },
];

const ANALYSTS = [
  { value: "market", label: "Market Analyst", description: "Technical analysis with indicators" },
  { value: "social", label: "Sentiment Analyst", description: "Social media sentiment" },
  { value: "news", label: "News Analyst", description: "Macro news and insider activity" },
  { value: "fundamentals", label: "Fundamentals Analyst", description: "Financial health metrics" },
];

function DecisionBadge({ decision }: { decision: string }) {
  const d = decision.toLowerCase();
  if (d === "buy" || d === "overweight") {
    return <span className="badge badge-buy"><TrendingUp size={12} /> {decision}</span>;
  }
  if (d === "sell" || d === "underweight") {
    return <span className="badge badge-sell"><TrendingDown size={12} /> {decision}</span>;
  }
  if (d === "hold") {
    return <span className="badge badge-neutral"><Minus size={12} /> {decision}</span>;
  }
  if (d === "error") {
    return <span className="badge badge-failure"><AlertCircle size={12} /> Error</span>;
  }
  return <span className="badge badge-running"><Clock size={12} /> {decision}</span>;
}

function ReportPanel({ title, content }: { title: string; content?: string }) {
  const [open, setOpen] = useState(false);
  if (!content) return null;
  return (
    <div className="panel" style={{ padding: 0 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "12px 16px",
          background: "transparent",
          border: "none",
          color: "var(--text-strong)",
          cursor: "pointer",
          font: "inherit",
          fontSize: 14,
          fontWeight: 600,
          textAlign: "left",
        }}
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {title}
      </button>
      {open && (
        <pre className="run-detail-pre" style={{ margin: 0, borderRadius: 0, borderTop: "1px solid var(--border)" }}>
          {content}
        </pre>
      )}
    </div>
  );
}

export default function TradingAgentsPage() {
  const [ticker, setTicker] = useState("NVDA");
  const [date, setDate] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [selectedAnalysts, setSelectedAnalysts] = useState(["market", "social", "news", "fundamentals"]);
  const [loading, setLoading] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [serviceAvailable, setServiceAvailable] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/trading-agents/health")
      .then(r => r.json())
      .then(d => setServiceAvailable(d.status === "ok"))
      .catch(() => setServiceAvailable(false));

    fetch("/api/trading-agents/results")
      .then(r => r.json())
      .then(d => { if (Array.isArray(d)) setHistory(d); })
      .catch(() => {});
  }, []);

  const pollStatus = useCallback((rid: string) => {
    const interval = setInterval(() => {
      fetch(`/api/trading-agents/status/${rid}`)
        .then(r => r.json())
        .then(data => {
          if (data.status === "completed" || data.status === "error") {
            clearInterval(interval);
            setResult(data);
            setLoading(false);
            fetch("/api/trading-agents/results")
              .then(r => r.json())
              .then(d => { if (Array.isArray(d)) setHistory(d); })
              .catch(() => {});
          }
        })
        .catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/trading-agents/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.toUpperCase(),
          date: date || undefined,
          llm_provider: provider,
          deep_think_llm: model,
          quick_think_llm: model,
          analysts: selectedAnalysts,
        }),
      });
      const data = await res.json();
      if (data.request_id) {
        setRequestId(data.request_id);
        pollStatus(data.request_id);
      } else {
        setError("Failed to start analysis");
        setLoading(false);
      }
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  };

  const toggleAnalyst = (value: string) => {
    setSelectedAnalysts(prev =>
      prev.includes(value) ? prev.filter(a => a !== value) : [...prev, value]
    );
  };

  return (
    <main className="page page-wide">
      <section className="hero">
        <div>
          <p className="eyebrow">AI Hedge Fund</p>
          <h1>Multi-agent stock analysis.</h1>
          <p>
            Powered by TradingAgents — 12 specialized AI agents analyze any stock through debate,
            risk management, and portfolio management to produce actionable recommendations.
          </p>
        </div>
        <div className="hero-actions">
          {serviceAvailable === true && <span className="badge badge-success">Service online</span>}
          {serviceAvailable === false && <span className="badge badge-failure">Service offline</span>}
          {serviceAvailable === null && <span className="badge badge-neutral">Checking...</span>}
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: result ? "380px 1fr" : "1fr", gap: 16 }}>
        {/* Analysis Form */}
        <section className="panel">
          <h3>Run Analysis</h3>

          {serviceAvailable === false && (
            <div className="form-error" style={{ marginBottom: 12 }}>
              <p>TradingAgents service is not running.</p>
              <p style={{ fontSize: 12, color: "var(--muted)" }}>
                Start it with: <code>cd apps/trading-agents && pip install -r requirements.txt && python main.py</code>
              </p>
            </div>
          )}

          <div style={{ display: "grid", gap: 12, marginTop: 8 }}>
            <div className="form-row">
              <label>
                Ticker Symbol
                <input
                  type="text"
                  value={ticker}
                  onChange={e => setTicker(e.target.value)}
                  placeholder="e.g. NVDA, AAPL, TSLA"
                />
              </label>
            </div>

            <div className="form-row">
              <label>
                Analysis Date (optional)
                <input
                  type="date"
                  value={date}
                  onChange={e => setDate(e.target.value)}
                />
              </label>
            </div>

            <div className="form-row">
              <label>
                LLM Provider
                <select value={provider} onChange={e => setProvider(e.target.value)}>
                  {PROVIDERS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="form-row">
              <label>
                Model
                <input
                  type="text"
                  value={model}
                  onChange={e => setModel(e.target.value)}
                  placeholder="gpt-4o-mini"
                />
              </label>
            </div>

            <div>
              <span className="label" style={{ marginBottom: 8, display: "block" }}>Analysts</span>
              <div className="checkbox-row" style={{ flexDirection: "column" }}>
                {ANALYSTS.map(a => (
                  <label key={a.value} className={`checkbox-label ${selectedAnalysts.includes(a.value) ? "" : ""}`}>
                    <input
                      type="checkbox"
                      checked={selectedAnalysts.includes(a.value)}
                      onChange={() => toggleAnalyst(a.value)}
                    />
                    <span style={{ display: "grid", gap: 1 }}>
                      <strong style={{ fontSize: 13 }}>{a.label}</strong>
                      <small style={{ color: "var(--muted)", fontSize: 11 }}>{a.description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <button
              className="btn btn-primary"
              onClick={runAnalysis}
              disabled={loading || !ticker.trim() || serviceAvailable === false}
              style={{ width: "100%", minHeight: 44 }}
            >
              {loading ? (
                <>Analyzing {ticker.toUpperCase()}...</>
              ) : (
                <><Play size={16} /> Analyze {ticker.toUpperCase()}</>
              )}
            </button>

            {error && <p className="feedback-error">{error}</p>}
          </div>
        </section>

        {/* Results */}
        {result && (
          <section style={{ display: "grid", gap: 12, alignContent: "start" }}>
            <div className="panel" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <span className="label">Final Recommendation</span>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 6 }}>
                  <span style={{ fontSize: 28, fontWeight: 700, color: "var(--text-strong)" }}>
                    {result.ticker}
                  </span>
                  <DecisionBadge decision={result.decision} />
                </div>
                <span className="muted" style={{ fontSize: 12, marginTop: 4, display: "block" }}>
                  Analysis date: {result.date}
                </span>
              </div>
            </div>

            <ReportPanel title="Market Analysis" content={result.market_report} />
            <ReportPanel title="Sentiment Analysis" content={result.sentiment_report} />
            <ReportPanel title="News Analysis" content={result.news_report} />
            <ReportPanel title="Fundamentals Analysis" content={result.fundamentals_report} />
            <ReportPanel title="Investment Plan" content={result.investment_plan} />
            <ReportPanel title="Trader Decision" content={result.trader_decision} />
            <ReportPanel title="Portfolio Manager Decision" content={result.final_decision} />
          </section>
        )}

        {/* Loading state */}
        {loading && !result && (
          <section className="panel" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, minHeight: 200 }}>
            <div style={{ width: 32, height: 32, border: "3px solid var(--border)", borderTopColor: "var(--accent)", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
            <p style={{ color: "var(--muted)", fontSize: 14 }}>
              Running multi-agent analysis on {ticker.toUpperCase()}...
            </p>
            <p style={{ color: "var(--muted-strong)", fontSize: 12 }}>
              This takes 1-3 minutes. Analysts are debating.
            </p>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </section>
        )}
      </div>

      {/* History */}
      {history.length > 0 && (
        <section style={{ marginTop: 24 }}>
          <h3 style={{ color: "var(--text-strong)", marginBottom: 12 }}>Previous Analyses</h3>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Date</th>
                  <th>Decision</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {history.map(h => (
                  <tr key={h.request_id}>
                    <td><strong>{h.ticker}</strong></td>
                    <td>{h.date}</td>
                    <td><DecisionBadge decision={h.decision} /></td>
                    <td><span className={`badge badge-${h.status === "completed" ? "success" : "failure"}`}>{h.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
