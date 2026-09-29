"use client";

// intent: the hero animation — one plain-English question becomes a typed strategy, a news scan, a real
//   backtest and an honest verdict. Every number comes from lib/cibr-hacks.json (real CIBR closes);
//   nothing here is invented. One clock `t` (ms) drives every stage, so the sequence is deterministic,
//   pauses off-screen, loops, and jumps to the end under prefers-reduced-motion.

import { useEffect, useMemo, useRef, useState } from "react";
import { DEMO, PLATFORMS, applyCosts, linePath, pct, scale, usd } from "@/lib/demo";

const PROMPT =
  "What if, over the last 5 years, I'd bought 1 share of CIBR every time a big hack made national news?";

const SPEC: [string, string][] = [
  ["asset", "CIBR · cybersecurity ETF"],
  ["trigger", "news · major hack, national"],
  ["entry", "buy 1 share · next close"],
  ["exit", "hold"],
  ["window", `${DEMO.window[0]} → ${DEMO.window[1]}`],
  ["costs", "Interactive Brokers"],
];

// Stage timeline (ms). Each stage starts when the previous one lands.
const T_TYPE = 0;
const CHAR_MS = 24;
const T_SPEC = T_TYPE + PROMPT.length * CHAR_MS + 350;
const SPEC_MS = 230;
const T_FEED = T_SPEC + SPEC.length * SPEC_MS + 250;
const FEED_MS = 105;
const T_CHART = T_FEED + DEMO.events.length * FEED_MS + 200;
const CHART_MS = 2400;
const T_KPI = T_CHART + CHART_MS + 150;
const T_END = T_KPI + 900;
const HOLD_MS = 9000;

const W = 640;
const H = 250;
const PAD = { l: 44, r: 10, t: 12, b: 24 };

export function HeroDemo() {
  const [t, setT] = useState(0);
  const [visible, setVisible] = useState(true);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setT(T_END);
      return;
    }
    const el = rootRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || t >= T_END + HOLD_MS) return;
    const id = window.setTimeout(() => setT((x) => x + 40), 40);
    return () => window.clearTimeout(id);
  }, [t, visible]);

  useEffect(() => {
    if (t >= T_END + HOLD_MS) setT(0); // loop
  }, [t]);

  const stage = t < T_SPEC ? 0 : t < T_FEED ? 1 : t < T_CHART ? 2 : t < T_KPI ? 3 : 4;
  const typed = PROMPT.slice(0, Math.max(0, Math.floor((t - T_TYPE) / CHAR_MS)));
  const specShown = Math.max(0, Math.floor((t - T_SPEC) / SPEC_MS) + 1);
  const feedShown = t < T_FEED ? 0 : Math.min(DEMO.events.length, Math.floor((t - T_FEED) / FEED_MS) + 1);

  const chart = useMemo(() => {
    const s = DEMO.series;
    const values = s.map((p) => p[1] * p[2]);
    const costs = s.map((p) => p[3]);
    const max = Math.max(...values, ...costs);
    const top = Math.ceil(max / 500) * 500;
    const x = scale([0, s.length - 1], [PAD.l, W - PAD.r]);
    const y = scale([0, top], [H - PAD.b, PAD.t]);
    const xs = s.map((_, i) => x(i));
    const vy = values.map(y);
    const cy = costs.map(y);
    const value = linePath(xs, vy);
    const area = `${value}L${xs[xs.length - 1]},${y(0)}L${xs[0]},${y(0)}Z`;
    const cost = linePath(xs, cy);
    const idx = new Map(s.map((p, i) => [p[0], i]));
    const marks = DEMO.events.map((e) => {
      const i = idx.get(e.fill) ?? 0;
      return { x: xs[i], y: vy[i], name: e.name };
    });
    const years: { x: number; label: string }[] = [];
    s.forEach((p, i) => {
      const yr = p[0].slice(0, 4);
      if (!years.length || years[years.length - 1].label !== yr) years.push({ x: xs[i], label: yr });
    });
    const ticks = Array.from({ length: top / 500 + 1 }, (_, k) => ({ y: y(k * 500), label: k ? `$${k * 500}` : "$0" }));
    return { value, area, cost, marks, years, ticks, x0: PAD.l, x1: W - PAD.r };
  }, []);

  const ibkr = useMemo(() => applyCosts(DEMO, PLATFORMS[0]), []);
  const st = DEMO.stats;
  const chartOn = t >= T_CHART;
  const kpiOn = t >= T_KPI;
  const restart = () => setT(0);

  return (
    <div ref={rootRef} className="cell console" aria-label="Animated demo: from a question to a backtest">
      <div className="console-bar">
        <div className="lights" aria-hidden>
          <i /> <i /> <i />
        </div>
        <span className="title">cosmu · research</span>
        <div className="right">
          <div className="steps" aria-hidden>
            {[0, 1, 2, 3, 4].map((k) => (
              <span key={k} className={stage >= k ? "on" : ""} />
            ))}
          </div>
          <button className="icon-btn" onClick={restart} aria-label="Replay the demo" title="Replay">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
              <path d="M3 3v5h5" />
            </svg>
          </button>
        </div>
      </div>

      <div className="console-body">
        <div className="console-side">
          <div className="prompt">
            <div className="who">You</div>
            {typed}
            {stage === 0 && <span className="caret" />}
          </div>

          <div>
            <div className="cell-label" style={{ marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
              <span>Strategy spec</span>
              {stage >= 1 && <span className="iris" style={{ textTransform: "none", letterSpacing: 0 }}>typed · validated</span>}
            </div>
            <div className="spec">
              {SPEC.map(([k, v], i) => (
                <div key={k} className={`spec-row ${stage >= 1 && i < specShown ? "show" : ""}`}>
                  <span className="k">{k}</span>
                  <span className="v">{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="cell-label" style={{ marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
              <span>News scan</span>
              <span className="mono" style={{ textTransform: "none", letterSpacing: 0, color: feedShown ? "var(--gold)" : undefined }}>
                {feedShown} / {DEMO.events.length} events
              </span>
            </div>
            <div className="feed" aria-live="off">
              {DEMO.events
                .slice(0, feedShown)
                .reverse()
                .map((e) => (
                  <div key={e.news + e.name} className="feed-item">
                    <span className="d">{e.news}</span>
                    <span className="t">{e.name}</span>
                  </div>
                ))}
            </div>
          </div>
        </div>

        <div className="console-main">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div className="cell-label">Backtest · portfolio value</div>
            <div className="legend">
              <span><i />value</span>
              <span><i className="c" />cash put in</span>
              <span><i className="m" />buy on hack news</span>
            </div>
          </div>

          <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Portfolio value versus money invested, 2021 to 2025">
            <defs>
              <linearGradient id="irisfade" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--iris)" stopOpacity="0.28" />
                <stop offset="1" stopColor="var(--iris)" stopOpacity="0" />
              </linearGradient>
              <clipPath id="reveal-clip">
                <rect x="0" y="0" height={H} width={W} style={{ transformOrigin: "0 0", transform: chartOn ? "scaleX(1)" : "scaleX(0)", transition: chartOn ? `transform ${CHART_MS}ms cubic-bezier(0.45,0,0.2,1)` : "none" }} />
              </clipPath>
            </defs>
            <g className="grid">
              {chart.ticks.map((k) => (
                <line key={k.label} x1={chart.x0} x2={chart.x1} y1={k.y} y2={k.y} />
              ))}
            </g>
            <g className="axis">
              {chart.ticks.map((k) => (
                <text key={k.label} x={chart.x0 - 8} y={k.y + 3} textAnchor="end">{k.label}</text>
              ))}
              {chart.years.map((yr) => (
                <text key={yr.label} x={yr.x} y={H - 6}>{yr.label}</text>
              ))}
            </g>
            <g clipPath="url(#reveal-clip)">
              <path className="area" d={chart.area} />
              <path className="cost" d={chart.cost} />
              <path className="value" d={chart.value} />
            </g>
            {chart.marks.map((m, i) => (
              <circle
                key={i}
                className={`mk pop ${chartOn ? "go" : ""}`}
                cx={m.x}
                cy={m.y}
                r={4}
                style={{ animationDelay: `${((m.x - chart.x0) / (chart.x1 - chart.x0)) * CHART_MS}ms` }}
              >
                <title>{m.name}</title>
              </circle>
            ))}
            {!chartOn && (
              <text x={W / 2} y={H / 2} textAnchor="middle" className="quiet" style={{ fill: "var(--quiet)", fontSize: 12 }}>
                {stage < 2 ? "waiting for a spec…" : "matching events to real prices…"}
              </text>
            )}
          </svg>

          <div className={`kpis fade ${kpiOn ? "show" : ""}`}>
            <div className="kpi">
              <div className="l">Cash put in → value</div>
              <div className="v">{usd(ibkr.value).replace(/\.\d+$/, "")}</div>
              <div className="s">from {usd(ibkr.invested).replace(/\.\d+$/, "")} over {st.trades} buys</div>
            </div>
            <div className="kpi">
              <div className="l">Return after fees</div>
              <div className="v up">{pct(ibkr.net)}</div>
              <div className="s">{usd(ibkr.fees)} fees + slippage</div>
            </div>
            <div className="kpi">
              <div className="l">Next 20 days, after a hack</div>
              <div className="v">{pct(st.avg_ret20_after_hack, 2)}</div>
              <div className="s">vs {pct(st.avg_ret20_any_day, 2)} on any day</div>
            </div>
            <div className="kpi">
              <div className="l">Beats random-date buying</div>
              <div className="v gold">{Math.round(st.pct_random_beaten * 100)}%</div>
              <div className="s">of 10,000 tries · bar is 95%</div>
            </div>
          </div>

          <div className={`verdict fade ${kpiOn ? "show" : ""}`} style={{ transitionDelay: "300ms" }}>
            <span className="chip gold" style={{ flexShrink: 0 }}>
              <span className="dot" /> No real edge
            </span>
            <span>
              It made money, but <b>not because of the hacks</b>. Buying on {st.trades} random days would have
              returned {pct(st.random_median_multiple - 1)} (median). The news adds{" "}
              {((st.avg_ret20_after_hack - st.avg_ret20_any_day) * 100).toFixed(2)} pts a month, which is inside the noise. Not fundable.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
