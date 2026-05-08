"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  GitBranch,
  Loader2,
  Minus,
  Newspaper,
  Play,
  RefreshCw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Users
} from "lucide-react";

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

type VersionInfo = {
  local: {
    version: string | null;
    tag: string | null;
    sourcePath: string | null;
    present: boolean;
  };
  latest: {
    tag: string | null;
    name: string | null;
    publishedAt: string | null;
    url: string | null;
  } | null;
  updateAvailable: boolean;
  releaseError: string | null;
};

const PROVIDERS = [
  { value: "openai", label: "OpenAI", model: "gpt-4o" },
  { value: "anthropic", label: "Anthropic", model: "claude-sonnet-4-5-20250929" },
  { value: "google", label: "Google", model: "gemini-2.5-flash" },
  { value: "mistral", label: "Mistral", model: "mistral-large-latest" },
  { value: "xai", label: "xAI", model: "grok-3-fast" },
  { value: "deepseek", label: "DeepSeek", model: "deepseek-chat" }
];

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini", "o3"],
  anthropic: ["claude-sonnet-4-5-20250929", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
  google: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
  mistral: ["mistral-large-latest", "mistral-small-latest", "codestral-latest"],
  xai: ["grok-3-fast", "grok-3", "grok-3-mini-fast"],
  deepseek: ["deepseek-chat", "deepseek-reasoner"]
};

const ANALYSTS = [
  { value: "market", label: "Market", description: "Charts and indicators", icon: BarChart3 },
  { value: "social", label: "Sentiment", description: "Social market mood", icon: Users },
  { value: "news", label: "News", description: "Headlines and macro", icon: Newspaper },
  { value: "fundamentals", label: "Fundamentals", description: "Financial health", icon: BookOpen }
];

const RUN_STEPS = [
  { label: "Analysts", description: "Market, sentiment, news, fundamentals" },
  { label: "Debate", description: "Bull and bear research" },
  { label: "Trader", description: "Action plan" },
  { label: "Risk", description: "Risk committee" },
  { label: "Portfolio", description: "Final decision" }
];

const REPORTS = [
  { key: "market_report", title: "Market Analysis" },
  { key: "sentiment_report", title: "Sentiment Analysis" },
  { key: "news_report", title: "News Analysis" },
  { key: "fundamentals_report", title: "Fundamentals Analysis" },
  { key: "investment_plan", title: "Investment Plan" },
  { key: "trader_decision", title: "Trader Decision" },
  { key: "final_decision", title: "Portfolio Manager" }
] as const;

const formatDate = (value?: string | null) => {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

const decisionTone = (decision: string) => {
  const d = decision.toLowerCase();
  if (d === "buy" || d === "overweight") return "buy";
  if (d === "sell" || d === "underweight") return "sell";
  if (d === "error") return "error";
  return "neutral";
};

function DecisionBadge({ decision }: { decision: string }) {
  const tone = decisionTone(decision);
  if (tone === "buy") {
    return <span className="badge badge-buy"><TrendingUp size={12} /> {decision}</span>;
  }
  if (tone === "sell") {
    return <span className="badge badge-sell"><TrendingDown size={12} /> {decision}</span>;
  }
  if (tone === "error") {
    return <span className="badge badge-failure"><AlertCircle size={12} /> Error</span>;
  }
  return <span className="badge badge-neutral"><Minus size={12} /> {decision || "Pending"}</span>;
}

function ReportPanel({ title, content }: { title: string; content?: string }) {
  const [open, setOpen] = useState(title === "Portfolio Manager");
  if (!content) return null;
  return (
    <section className="ta-report">
      <button type="button" className="ta-report-head" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
      </button>
      {open ? <pre className="run-detail-pre ta-report-body">{content}</pre> : null}
    </section>
  );
}

function VersionButton() {
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(false);

  const loadVersion = async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/trading-agents/version", { cache: "no-store" });
      const data = await response.json();
      setVersion(data);
    } catch {
      setVersion(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadVersion();
  }, []);

  return (
    <div className="ta-version-wrap">
      <button type="button" className="ta-version-button" onClick={() => setOpen((value) => !value)}>
        <GitBranch size={13} />
        <span>{version?.local.tag ?? "version"}</span>
        {version?.updateAvailable ? <span className="ta-version-dot" /> : null}
      </button>

      {open ? (
        <div className="ta-version-popover">
          <div className="ta-version-popover-head">
            <strong>TradingAgents</strong>
            <button type="button" className="ta-icon-button" onClick={loadVersion} aria-label="Refresh TradingAgents version">
              {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
            </button>
          </div>
          <div className="ta-version-row">
            <span>Local</span>
            <strong>{version?.local.tag ?? "not found"}</strong>
          </div>
          <div className="ta-version-row">
            <span>Latest</span>
            <strong>{version?.latest?.tag ?? "unavailable"}</strong>
          </div>
          <p className={version?.updateAvailable ? "ta-update-copy ta-update-copy-hot" : "ta-update-copy"}>
            {version?.updateAvailable
              ? "A newer GitHub release is available. Update manually after testing."
              : version?.releaseError
                ? version.releaseError
                : "Local copy is up to date with the latest release."}
          </p>
          {version?.latest?.url ? (
            <a className="ta-release-link" href={version.latest.url} target="_blank" rel="noreferrer">
              View release <ExternalLink size={13} />
            </a>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function TradingAgentsPage() {
  const [ticker, setTicker] = useState("NVDA");
  const [date, setDate] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o");
  const [selectedAnalysts, setSelectedAnalysts] = useState(["market", "social", "news", "fundamentals"]);
  const [loading, setLoading] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [serviceAvailable, setServiceAvailable] = useState<boolean | null>(null);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedProvider = PROVIDERS.find((item) => item.value === provider);

  const loadHealth = useCallback(async () => {
    try {
      const response = await fetch("/api/trading-agents/health", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) {
        setServiceAvailable(false);
        setServiceError("Start the TradingAgents wrapper on port 8100.");
        return;
      }
      setServiceAvailable(data.status === "ok");
      setServiceError(data.status === "ok" ? null : "Start the TradingAgents wrapper on port 8100.");
    } catch {
      setServiceAvailable(false);
      setServiceError("Start the TradingAgents wrapper on port 8100.");
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch("/api/trading-agents/results", { cache: "no-store" });
      const data = await response.json();
      setHistory(Array.isArray(data) ? data : []);
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    void loadHistory();
  }, [loadHealth, loadHistory]);

  const pollStatus = useCallback((rid: string) => {
    const interval = window.setInterval(() => {
      fetch(`/api/trading-agents/status/${rid}`, { cache: "no-store" })
        .then((response) => response.json())
        .then((data) => {
          if (data.status === "completed" || data.status === "error") {
            window.clearInterval(interval);
            setResult(data);
            setLoading(false);
            void loadHistory();
          }
        })
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(interval);
  }, [loadHistory]);

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/trading-agents/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.toUpperCase(),
          date: date || undefined,
          llm_provider: provider,
          deep_think_llm: model,
          quick_think_llm: model,
          analysts: selectedAnalysts
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? "Failed to start analysis");
      if (data.request_id) {
        setRequestId(data.request_id);
        pollStatus(data.request_id);
      } else {
        throw new Error("TradingAgents did not return a request id");
      }
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to start analysis");
      setLoading(false);
    }
  };

  const toggleAnalyst = (value: string) => {
    setSelectedAnalysts((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
    );
  };

  const reportCount = useMemo(() => {
    if (!result) return 0;
    return REPORTS.filter((report) => Boolean(result[report.key])).length;
  }, [result]);

  return (
    <main className="page page-wide ta-page">
      <section className="ta-hero">
        <div className="ta-hero-main">
          <p className="eyebrow">AI Hedge Fund</p>
          <h1>Run TradingAgents without leaving Cosmu.</h1>
          <p>
            A clean front end for the local TauricResearch TradingAgents engine: analysts, debate,
            risk review, and a final portfolio-manager recommendation.
          </p>
        </div>
        <div className="ta-hero-actions">
          <VersionButton />
          {serviceAvailable === true ? <span className="badge badge-success">Service online</span> : null}
          {serviceAvailable === false ? <span className="badge badge-failure">Service offline</span> : null}
          {serviceAvailable === null ? <span className="badge badge-neutral">Checking</span> : null}
        </div>
      </section>

      <div className="ta-layout">
        <aside className="ta-run-panel">
          <section className="panel ta-sticky">
            <div className="section-header">
              <div>
                <h3>New analysis</h3>
                <p className="muted">Stocks only. Results are research output, not execution.</p>
              </div>
              <button type="button" className="ta-icon-button" onClick={loadHealth} aria-label="Refresh TradingAgents service status">
                <RefreshCw size={15} />
              </button>
            </div>

            {serviceAvailable === false ? (
              <div className="ta-service-warning">
                <AlertCircle size={16} />
                <span>
                  <strong>Service is not running</strong>
                  <small>{serviceError ?? "Start the TradingAgents wrapper on port 8100."}</small>
                </span>
              </div>
            ) : null}

            <div className="ta-form-grid">
              <label className="field">
                <span>Ticker</span>
                <input
                  type="text"
                  value={ticker}
                  onChange={(event) => setTicker(event.target.value.toUpperCase())}
                  placeholder="NVDA"
                />
              </label>

              <label className="field">
                <span>Date</span>
                <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
              </label>

              <label className="field">
                <span>Provider</span>
                <select
                  value={provider}
                  onChange={(event) => {
                    const nextProvider = event.target.value;
                    setProvider(nextProvider);
                    setModel(PROVIDERS.find((item) => item.value === nextProvider)?.model ?? model);
                  }}
                >
                  {PROVIDERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>

              <label className="field">
                <span>Model</span>
                <select value={model} onChange={(event) => setModel(event.target.value)}>
                  {(MODELS_BY_PROVIDER[provider] ?? []).map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="ta-analysts">
              <span className="label">Analysts</span>
              <div className="ta-analyst-grid">
                {ANALYSTS.map((analyst) => {
                  const Icon = analyst.icon;
                  const checked = selectedAnalysts.includes(analyst.value);
                  return (
                    <button
                      key={analyst.value}
                      type="button"
                      className={`ta-analyst-option ${checked ? "ta-analyst-option-active" : ""}`}
                      onClick={() => toggleAnalyst(analyst.value)}
                      aria-pressed={checked}
                    >
                      <Icon size={16} />
                      <span>
                        <strong>{analyst.label}</strong>
                        <small>{analyst.description}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <button
              className="btn btn-primary ta-run-button"
              type="button"
              onClick={runAnalysis}
              disabled={loading || !ticker.trim() || selectedAnalysts.length === 0 || serviceAvailable === false}
            >
              {loading ? <><Loader2 size={16} className="spin" /> Running {ticker}</> : <><Play size={16} /> Run analysis</>}
            </button>

            {error ? <p className="feedback-error ta-error">{error}</p> : null}

            <div className="ta-run-meta">
              <span><Brain size={14} /> {selectedProvider?.label ?? provider}</span>
              <span><ShieldCheck size={14} /> {selectedAnalysts.length} analysts</span>
            </div>
          </section>
        </aside>

        <section className="ta-workspace">
          {loading ? (
            <section className="panel ta-progress-panel">
              <div className="ta-progress-head">
                <Loader2 size={20} className="spin" />
                <span>
                  <strong>Running {ticker}</strong>
                  <small>{requestId ? `Request ${requestId}` : "Waiting for request id"}</small>
                </span>
              </div>
              <div className="ta-progress-list">
                {RUN_STEPS.map((step, index) => (
                  <div className="ta-progress-step" key={step.label}>
                    <span className={index === 0 ? "ta-progress-dot ta-progress-dot-active" : "ta-progress-dot"} />
                    <span>
                      <strong>{step.label}</strong>
                      <small>{step.description}</small>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {result ? (
            <section className="ta-results">
              <div className="panel ta-result-summary">
                <div>
                  <span className="label">Final recommendation</span>
                  <div className="ta-result-title">
                    <strong>{result.ticker}</strong>
                    <DecisionBadge decision={result.decision} />
                  </div>
                  <small className="muted">Analysis date: {result.date}</small>
                </div>
                <div className="ta-result-stats">
                  <span><CheckCircle2 size={14} /> {reportCount} reports</span>
                  <span><Clock size={14} /> {result.status}</span>
                </div>
              </div>

              {REPORTS.map((report) => (
                <ReportPanel key={report.key} title={report.title} content={result[report.key]} />
              ))}
            </section>
          ) : null}

          {!loading && !result ? (
            <section className="panel ta-empty-state">
              <TrendingUp size={24} />
              <span>
                <strong>Ready when the local engine is online.</strong>
                <small>Run a ticker to get analyst reports, debate output, risk review, and a final decision in one place.</small>
              </span>
            </section>
          ) : null}

          <section className="panel ta-history-panel">
            <div className="section-header">
              <div>
                <h3>Previous analyses</h3>
                <p className="muted">Recent TradingAgents outputs from the local service.</p>
              </div>
              <span className="badge badge-neutral">{history.length} saved</span>
            </div>

            {history.length > 0 ? (
              <div className="ta-history-grid">
                {history.map((item) => (
                  <article key={item.request_id} className="ta-history-card">
                    <span>
                      <strong>{item.ticker}</strong>
                      <small>{formatDate(item.date)}</small>
                    </span>
                    <DecisionBadge decision={item.decision} />
                    <small className="muted">{item.status}</small>
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted">No completed analyses yet.</p>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
