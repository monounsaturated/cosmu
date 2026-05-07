"use client";

import { useState, useEffect } from "react";
import { BarChart3, TrendingUp, TrendingDown, Zap, MessageSquare, Send } from "lucide-react";

type PromptVersion = {
  id: string;
  promptName: string;
  body: string;
  createdAt: string;
};

type PromptPerformance = {
  promptName: string;
  totalRuns: number;
  successRate: number;
  avgConfidence: number;
  profitableRuns: number;
  totalPnl: number;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export default function PromptLabPage() {
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [performance, setPerformance] = useState<PromptPerformance[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "I'm your prompt optimization assistant. I can analyze your prompt history, compare performance across versions, and suggest improvements. What would you like to explore?" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/prompts")
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        if (Array.isArray(data)) {
          const flat = data.flatMap((p: { name: string; versions: Array<{ id: string; body: string; createdAt: string }> }) =>
            (p.versions || []).map((v: { id: string; body: string; createdAt: string }) => ({
              id: v.id,
              promptName: p.name,
              body: v.body,
              createdAt: v.createdAt,
            }))
          );
          setVersions(flat.slice(0, 50));
        }
      })
      .catch(() => {});

    fetch("/api/dashboard")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.bots) return;
        const perfMap = new Map<string, PromptPerformance>();
        for (const bot of data.bots) {
          const name = bot.researchPromptName || bot.promptName || "default";
          const existing = perfMap.get(name) || {
            promptName: name,
            totalRuns: 0,
            successRate: 0,
            avgConfidence: 0,
            profitableRuns: 0,
            totalPnl: 0,
          };
          existing.totalRuns += bot.runCount || 0;
          existing.totalPnl += bot.netPnlUsd || 0;
          existing.profitableRuns += (bot.netPnlUsd ?? 0) > 0 ? 1 : 0;
          perfMap.set(name, existing);
        }
        setPerformance(Array.from(perfMap.values()));
      })
      .catch(() => {});
  }, []);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg: ChatMessage = { role: "user", content: input.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const context = `Prompt versions: ${versions.length}. Performance data: ${JSON.stringify(performance.slice(0, 10))}. Latest prompts: ${versions.slice(0, 5).map(v => `${v.promptName} (${v.createdAt})`).join(", ")}`;

    const response: ChatMessage = {
      role: "assistant",
      content: generateLocalResponse(userMsg.content, context, performance, versions),
    };

    setTimeout(() => {
      setMessages(prev => [...prev, response]);
      setLoading(false);
    }, 600);
  };

  return (
    <main className="page page-wide">
      <section className="hero">
        <div>
          <p className="eyebrow">Prompt Lab</p>
          <h1>Iterate and optimize prompts.</h1>
          <p>
            Analyze prompt performance, compare versions, and get AI-powered suggestions
            to improve your trading agent prompts.
          </p>
        </div>
        <div className="hero-actions">
          <span className="badge badge-neutral">{versions.length} versions</span>
          <span className="badge badge-neutral">{performance.length} prompts tracked</span>
        </div>
      </section>

      {/* Performance Overview */}
      {performance.length > 0 && (
        <section className="metric-strip" style={{ gridTemplateColumns: `repeat(${Math.min(performance.length, 4)}, 1fr)` }}>
          {performance.slice(0, 4).map(p => (
            <article key={p.promptName}>
              <span>{p.promptName}</span>
              <strong className={p.totalPnl >= 0 ? "value-green" : "value-red"}>
                {p.totalPnl >= 0 ? "+" : ""}${p.totalPnl.toFixed(2)}
              </strong>
              <small>{p.totalRuns} runs</small>
            </article>
          ))}
        </section>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16 }}>
        {/* Chat Interface */}
        <section className="panel" style={{ display: "flex", flexDirection: "column", minHeight: 500, padding: 0 }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 8 }}>
            <MessageSquare size={16} />
            <strong style={{ fontSize: 14 }}>Prompt Advisor</strong>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
            {messages.map((msg, i) => (
              <div
                key={i}
                style={{
                  alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "85%",
                  padding: "10px 14px",
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
            {loading && (
              <div style={{ alignSelf: "flex-start", padding: "10px 14px", borderRadius: "var(--radius-sm)", background: "var(--surface)", color: "var(--muted)", fontSize: 13 }}>
                Thinking...
              </div>
            )}
          </div>

          <form
            onSubmit={e => { e.preventDefault(); sendMessage(); }}
            style={{ display: "flex", gap: 8, padding: 12, borderTop: "1px solid var(--border)" }}
          >
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask about prompt performance, suggest improvements..."
              style={{
                flex: 1,
                minHeight: 40,
                padding: "8px 12px",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text)",
                fontSize: 14,
                fontFamily: "inherit",
                outline: "none",
              }}
            />
            <button className="btn btn-primary" type="submit" disabled={loading || !input.trim()}>
              <Send size={16} />
            </button>
          </form>
        </section>

        {/* Prompt Version History */}
        <section style={{ display: "grid", gap: 8, alignContent: "start" }}>
          <h3 style={{ color: "var(--text-strong)", fontSize: 14 }}>Version History</h3>
          {versions.length === 0 ? (
            <div className="panel">
              <p className="muted">No prompt versions found. Create prompts in the Settings page to track them here.</p>
            </div>
          ) : (
            versions.slice(0, 20).map(v => (
              <button
                key={v.id}
                className={`dense-row ${selectedPrompt === v.id ? "dense-row-active" : ""}`}
                onClick={() => setSelectedPrompt(selectedPrompt === v.id ? null : v.id)}
              >
                <span>
                  <strong style={{ fontSize: 13 }}>{v.promptName}</strong>
                  <span className="muted" style={{ fontSize: 11 }}>
                    {new Date(v.createdAt).toLocaleDateString()}
                  </span>
                </span>
                <Zap size={14} style={{ color: "var(--muted-strong)" }} />
              </button>
            ))
          )}

          {selectedPrompt && (() => {
            const v = versions.find(v => v.id === selectedPrompt);
            if (!v) return null;
            return (
              <div className="panel" style={{ marginTop: 4 }}>
                <span className="label">{v.promptName}</span>
                <pre className="run-detail-pre" style={{ marginTop: 8, maxHeight: 200 }}>
                  {v.body}
                </pre>
              </div>
            );
          })()}
        </section>
      </div>
    </main>
  );
}

function generateLocalResponse(
  question: string,
  context: string,
  performance: PromptPerformance[],
  versions: PromptVersion[]
): string {
  const q = question.toLowerCase();

  if (q.includes("best") || q.includes("top") || q.includes("performance")) {
    if (performance.length === 0) return "No performance data yet. Run some agents and I'll be able to compare prompt effectiveness.";
    const sorted = [...performance].sort((a, b) => b.totalPnl - a.totalPnl);
    const best = sorted[0];
    return `Based on current data, "${best.promptName}" is performing best with $${best.totalPnl.toFixed(2)} PnL across ${best.totalRuns} runs.\n\n${sorted.length > 1 ? `Comparison:\n${sorted.map((p, i) => `${i + 1}. ${p.promptName}: $${p.totalPnl.toFixed(2)} (${p.totalRuns} runs)`).join("\n")}` : ""}`;
  }

  if (q.includes("suggest") || q.includes("improve") || q.includes("optimize")) {
    return `Here are some prompt optimization strategies:\n\n1. **Be specific about timeframes** — specify whether the agent should focus on intraday, swing, or position trading\n2. **Add risk constraints** — include explicit max position size and drawdown limits in the prompt\n3. **Reduce hallucination** — add grounding rules like "only cite data you retrieved"\n4. **Separate concerns** — use different prompts for research (free-form) vs execution (structured)\n5. **Version and A/B test** — run the same market conditions with different prompts to compare\n\nWant me to analyze a specific prompt in detail?`;
  }

  if (q.includes("version") || q.includes("history") || q.includes("how many")) {
    return `You have ${versions.length} prompt versions across ${new Set(versions.map(v => v.promptName)).size} prompts.\n\nLatest versions:\n${versions.slice(0, 5).map(v => `- ${v.promptName} (${new Date(v.createdAt).toLocaleDateString()})`).join("\n")}`;
  }

  if (q.includes("compare")) {
    if (performance.length < 2) return "Need at least 2 prompts with run data to compare. Create more agent variations first.";
    const sorted = [...performance].sort((a, b) => b.totalPnl - a.totalPnl);
    return `Prompt comparison:\n\n${sorted.map((p, i) => `**${i + 1}. ${p.promptName}**\n   PnL: $${p.totalPnl.toFixed(2)} | Runs: ${p.totalRuns}`).join("\n\n")}\n\nThe top performer has ${((sorted[0].totalPnl - sorted[sorted.length - 1].totalPnl)).toFixed(2)} more PnL than the worst.`;
  }

  return `I can help you with:\n\n- **"Which prompt performs best?"** — compare PnL across prompt versions\n- **"Suggest improvements"** — get optimization strategies\n- **"Compare prompts"** — side-by-side prompt analysis\n- **"Show version history"** — see all prompt iterations\n\nWhat would you like to know?`;
}
