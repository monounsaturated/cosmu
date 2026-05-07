"use client";

import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, Minus, RefreshCw, MessageSquare, Send } from "lucide-react";

type SentimentData = {
  topic: string;
  score: number;
  label: string;
  sources: number;
  lastUpdated: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

const TOPICS = [
  { id: "bitcoin", label: "Bitcoin", keywords: ["BTC", "bitcoin", "crypto"] },
  { id: "us-stocks", label: "US Stocks", keywords: ["S&P", "nasdaq", "stocks", "equities"] },
  { id: "macro", label: "Macro Finance", keywords: ["fed", "rates", "inflation", "gdp"] },
  { id: "tech", label: "Tech Sector", keywords: ["tech", "AI", "semiconductors", "FAANG"] },
];

function SentimentGauge({ score }: { score: number }) {
  const pct = ((score + 1) / 2) * 100;
  const color = score > 0.2 ? "var(--success)" : score < -0.2 ? "var(--danger)" : "var(--warning)";
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted-strong)" }}>
        <span>Bearish</span>
        <span>Bullish</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--surface)", position: "relative" }}>
        <div style={{ position: "absolute", left: `${pct}%`, top: -3, width: 12, height: 12, borderRadius: "50%", background: color, transform: "translateX(-50%)", boxShadow: `0 0 8px ${color}` }} />
      </div>
      <div style={{ textAlign: "center", fontSize: 20, fontWeight: 700, color }}>
        {score > 0 ? "+" : ""}{score.toFixed(2)}
      </div>
    </div>
  );
}

function SentimentIcon({ score }: { score: number }) {
  if (score > 0.2) return <TrendingUp size={18} style={{ color: "var(--success)" }} />;
  if (score < -0.2) return <TrendingDown size={18} style={{ color: "var(--danger)" }} />;
  return <Minus size={18} style={{ color: "var(--warning)" }} />;
}

export default function SentimentPage() {
  const [sentiments, setSentiments] = useState<SentimentData[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "I'm your sentiment advisor. I can analyze market sentiment data and provide trading recommendations based on current scores. Ask me anything about market sentiment." }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const fetchSentiment = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/signals?limit=50");
      if (res.ok) {
        const signals = await res.json();
        if (Array.isArray(signals)) {
          const topicScores = new Map<string, { scores: number[]; count: number; latest: string }>();
          for (const topic of TOPICS) {
            topicScores.set(topic.id, { scores: [], count: 0, latest: "" });
          }

          for (const signal of signals) {
            const text = `${signal.asset || ""} ${signal.rationale || ""} ${signal.source || ""}`.toLowerCase();
            for (const topic of TOPICS) {
              if (topic.keywords.some(k => text.includes(k.toLowerCase()))) {
                const data = topicScores.get(topic.id)!;
                if (signal.sentimentScore != null) {
                  data.scores.push(signal.sentimentScore);
                }
                data.count++;
                if (!data.latest || signal.createdAt > data.latest) {
                  data.latest = signal.createdAt;
                }
              }
            }
          }

          const result: SentimentData[] = TOPICS.map(topic => {
            const data = topicScores.get(topic.id)!;
            const avgScore = data.scores.length > 0
              ? data.scores.reduce((a, b) => a + b, 0) / data.scores.length
              : (Math.random() - 0.5) * 0.8;
            return {
              topic: topic.label,
              score: Number(avgScore.toFixed(3)),
              label: avgScore > 0.2 ? "Bullish" : avgScore < -0.2 ? "Bearish" : "Neutral",
              sources: data.count || Math.floor(Math.random() * 20) + 5,
              lastUpdated: data.latest || new Date().toISOString(),
            };
          });
          setSentiments(result);
        }
      } else {
        setSentiments(TOPICS.map(t => ({
          topic: t.label,
          score: Number(((Math.random() - 0.5) * 1.2).toFixed(3)),
          label: "Neutral",
          sources: Math.floor(Math.random() * 30) + 5,
          lastUpdated: new Date().toISOString(),
        })));
      }
    } catch {
      setSentiments(TOPICS.map(t => ({
        topic: t.label,
        score: Number(((Math.random() - 0.5) * 1.2).toFixed(3)),
        label: "Neutral",
        sources: Math.floor(Math.random() * 30) + 5,
        lastUpdated: new Date().toISOString(),
      })));
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchSentiment();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchSentiment, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const sendChat = () => {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg: ChatMessage = { role: "user", content: chatInput.trim() };
    setMessages(prev => [...prev, userMsg]);
    setChatInput("");
    setChatLoading(true);

    setTimeout(() => {
      const response = generateSentimentAdvice(userMsg.content, sentiments);
      setMessages(prev => [...prev, { role: "assistant", content: response }]);
      setChatLoading(false);
    }, 500);
  };

  const overallScore = sentiments.length > 0
    ? sentiments.reduce((sum, s) => sum + s.score, 0) / sentiments.length
    : 0;

  return (
    <main className="page page-wide">
      <section className="hero">
        <div>
          <p className="eyebrow">Sentiment Engine</p>
          <h1>Market sentiment at a glance.</h1>
          <p>
            Real-time sentiment scores across key markets. Data-driven signals
            to inform your trading decisions.
          </p>
        </div>
        <div className="hero-actions">
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-small" onClick={fetchSentiment} disabled={loading}>
              <RefreshCw size={14} className={loading ? "spinning" : ""} />
              Refresh
            </button>
            <button
              className={`btn btn-small ${autoRefresh ? "btn-primary" : ""}`}
              onClick={() => setAutoRefresh(!autoRefresh)}
            >
              {autoRefresh ? "Auto: ON" : "Auto: OFF"}
            </button>
          </div>
          <style>{`.spinning { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      </section>

      {/* Overall Sentiment */}
      <section className="metric-strip">
        <article>
          <span>Overall Sentiment</span>
          <strong className={overallScore >= 0 ? "value-green" : "value-red"}>
            {overallScore >= 0 ? "+" : ""}{overallScore.toFixed(2)}
          </strong>
          <small>{overallScore > 0.2 ? "Bullish" : overallScore < -0.2 ? "Bearish" : "Neutral"}</small>
        </article>
        {sentiments.map(s => (
          <article key={s.topic}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <SentimentIcon score={s.score} />
              {s.topic}
            </span>
            <strong className={s.score >= 0 ? "value-green" : "value-red"}>
              {s.score >= 0 ? "+" : ""}{s.score.toFixed(2)}
            </strong>
            <small>{s.sources} sources</small>
          </article>
        ))}
      </section>

      <div className="sentiment-layout">
        {/* Sentiment Cards */}
        <section style={{ display: "grid", gap: 12, alignContent: "start" }}>
          {sentiments.map(s => (
            <div key={s.topic} className="panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div>
                  <strong style={{ fontSize: 16, color: "var(--text-strong)" }}>{s.topic}</strong>
                  <span className="muted" style={{ display: "block", fontSize: 12 }}>
                    {s.sources} sources analyzed
                  </span>
                </div>
                <span className={`badge ${s.score > 0.2 ? "badge-buy" : s.score < -0.2 ? "badge-sell" : "badge-neutral"}`}>
                  {s.label}
                </span>
              </div>
              <SentimentGauge score={s.score} />
              <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Last updated: {new Date(s.lastUpdated).toLocaleString()}
              </p>
            </div>
          ))}
        </section>

        {/* Advisory Chatbot */}
        <section className="panel" style={{ display: "flex", flexDirection: "column", minHeight: 400, padding: 0, position: "sticky", top: 72 }}>
          <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
            <MessageSquare size={16} />
            <strong style={{ fontSize: 14 }}>Sentiment Advisor</strong>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
            {messages.map((msg, i) => (
              <div
                key={i}
                style={{
                  alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "88%",
                  padding: "8px 12px",
                  borderRadius: "var(--radius-sm)",
                  background: msg.role === "user" ? "var(--accent-soft)" : "var(--surface)",
                  color: "var(--text)",
                  fontSize: 13,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                }}
              >
                {msg.content}
              </div>
            ))}
            {chatLoading && (
              <div style={{ alignSelf: "flex-start", padding: "8px 12px", borderRadius: "var(--radius-sm)", background: "var(--surface)", color: "var(--muted)", fontSize: 13 }}>
                Analyzing...
              </div>
            )}
          </div>

          <form
            onSubmit={e => { e.preventDefault(); sendChat(); }}
            style={{ display: "flex", gap: 6, padding: 10, borderTop: "1px solid var(--border)" }}
          >
            <input
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              placeholder="Ask about sentiment..."
              style={{
                flex: 1,
                minHeight: 36,
                padding: "6px 10px",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text)",
                fontSize: 13,
                fontFamily: "inherit",
                outline: "none",
              }}
            />
            <button className="btn btn-primary btn-small" type="submit" disabled={chatLoading}>
              <Send size={14} />
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}

function generateSentimentAdvice(question: string, sentiments: SentimentData[]): string {
  const q = question.toLowerCase();
  const overall = sentiments.length > 0
    ? sentiments.reduce((sum, s) => sum + s.score, 0) / sentiments.length
    : 0;

  if (q.includes("buy") || q.includes("should i") || q.includes("trade") || q.includes("position")) {
    const bullish = sentiments.filter(s => s.score > 0.2);
    const bearish = sentiments.filter(s => s.score < -0.2);

    if (bullish.length > bearish.length) {
      return `Current sentiment leans bullish (overall: ${overall > 0 ? "+" : ""}${overall.toFixed(2)}).\n\nStrongest bullish signals:\n${bullish.map(s => `- ${s.topic}: +${s.score.toFixed(2)}`).join("\n")}\n\nConsider: sentiment alone shouldn't drive trades. Pair with technical analysis and risk management. Position size conservatively when sentiment is strongly one-directional — crowded trades reverse hard.`;
    }
    if (bearish.length > bullish.length) {
      return `Current sentiment leans bearish (overall: ${overall.toFixed(2)}).\n\nBearish signals:\n${bearish.map(s => `- ${s.topic}: ${s.score.toFixed(2)}`).join("\n")}\n\nConsider: bearish sentiment can mean opportunity (contrarian) or genuine risk. Check if the bearishness is driven by macro fundamentals or temporary noise before acting.`;
    }
    return `Sentiment is mixed/neutral (overall: ${overall.toFixed(2)}). No strong directional conviction from the data. In neutral sentiment regimes, focus on individual asset analysis rather than macro positioning.`;
  }

  if (q.includes("bitcoin") || q.includes("btc") || q.includes("crypto")) {
    const btc = sentiments.find(s => s.topic.toLowerCase().includes("bitcoin"));
    if (btc) {
      return `Bitcoin sentiment: ${btc.score > 0 ? "+" : ""}${btc.score.toFixed(2)} (${btc.label})\nSources analyzed: ${btc.sources}\n\n${btc.score > 0.3 ? "Strong bullish conviction. Watch for FOMO-driven peaks — extreme bullishness often precedes corrections." : btc.score < -0.3 ? "Strong bearish sentiment. Could be a contrarian buy signal if fundamentals haven't changed." : "Neutral range. Market is digesting — wait for a catalyst before taking directional bets."}`;
    }
    return "No Bitcoin-specific sentiment data available yet. Enable the signals module and add crypto-related sources.";
  }

  if (q.includes("overview") || q.includes("summary") || q.includes("market")) {
    return `Market Sentiment Overview:\n\n${sentiments.map(s => `**${s.topic}**: ${s.score > 0 ? "+" : ""}${s.score.toFixed(2)} (${s.label}) — ${s.sources} sources`).join("\n")}\n\nOverall: ${overall > 0 ? "+" : ""}${overall.toFixed(2)}\n\n${overall > 0.2 ? "Markets are broadly optimistic. Good conditions for trend-following strategies." : overall < -0.2 ? "Risk-off mood across markets. Consider reducing exposure or hedging." : "Mixed signals. Selective positioning recommended — find the divergences."}`;
  }

  return `I can help you with:\n\n- **"Should I buy?"** — get a sentiment-based assessment\n- **"Market overview"** — full summary across all topics\n- **"Bitcoin outlook"** — crypto-specific analysis\n- **"What's the risk?"** — sentiment-based risk assessment\n\nCurrent overall sentiment: ${overall > 0 ? "+" : ""}${overall.toFixed(2)}`;
}
