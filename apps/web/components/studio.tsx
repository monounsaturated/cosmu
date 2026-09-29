"use client";

// intent: the hero — a plain-English question becomes a news scan, a backtest and a verdict. The intro
//   plays ONCE when the page opens (one clock `t`, ~6s), then everything stays still and interactive:
//   switch idea, switch broker, hover a trigger. Reduced motion or any click
//   jumps straight to the end. Every number is derived from lib/showcase.json (real closes).

import { useEffect, useMemo, useState } from "react";
import {
  IDEAS,
  fmtDate,
  holdWords,
  money,
  pct,
  platformsFor,
  randomWords,
  results,
  triggerWord,
  verdict,
  type Idea,
} from "@/lib/showcase";
import { Icon } from "./icon";

const STEPS = ["Reading your idea", "Scanning 6 years of news", "Pulling real prices", "Backtesting with your fees", "Luck test · 10,000 random dates"];

// Intro timeline (ms)
const TYPE_MS = 26;
const T_STEPS = 1900;
const STEP_MS = 520;
const T_SCAN = T_STEPS + STEP_MS;
const CARD_MS = 130;
const T_CHART = T_STEPS + STEP_MS * 2;
const CHART_MS = 1400;
const T_RESULT = T_STEPS + STEP_MS * 4 + 200;
const COUNT_MS = 700;
const T_END = T_RESULT + COUNT_MS + 100;

const W = 600;
const H = 210;
const PAD = { l: 8, r: 8, t: 12, b: 22 };

export function Studio() {
  const [key, setKey] = useState(IDEAS[0].key);
  const idea = IDEAS.find((i) => i.key === key) as Idea;
  const plats = platformsFor(idea);
  const [platId, setPlatId] = useState(plats[0].id);
  const plat = plats.find((p) => p.id === platId) ?? plats[0];
  const [t, setT] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  // Play the intro once, on arrival.
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setT(T_END);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const x = now - start;
      setT(Math.min(x, T_END));
      if (x < T_END) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const done = t >= T_END;
  const skip = () => setT(T_END);

  const pick = (k: string) => {
    skip();
    const next = IDEAS.find((i) => i.key === k);
    if (!next) return;
    setPlatId((cur) => (platformsFor(next).some((p) => p.id === cur) ? cur : platformsFor(next)[0].id));
    setKey(k);
    setHover(null);
  };

  const typed = done ? idea.ask : idea.ask.slice(0, Math.floor(t / TYPE_MS));
  const step = done ? STEPS.length : t < T_STEPS ? -1 : Math.min(STEPS.length, Math.floor((t - T_STEPS) / STEP_MS));
  const cards = done ? idea.trades.length : t < T_SCAN ? 0 : Math.min(idea.trades.length, Math.floor((t - T_SCAN) / CARD_MS) + 1);
  const chartP = done ? 1 : Math.max(0, Math.min(1, (t - T_CHART) / CHART_MS));
  const resP = done ? 1 : Math.max(0, Math.min(1, (t - T_RESULT) / COUNT_MS));
  const ease = 1 - Math.pow(1 - resP, 3);

  const r = results(idea, plat);
  const n = idea.trades.length;

  const chart = useMemo(() => {
    const s = idea.series;
    const ps = s.map((d) => d[1]);
    const lo = Math.min(...ps);
    const hi = Math.max(...ps);
    const x = (i: number) => PAD.l + (i / (s.length - 1)) * (W - PAD.l - PAD.r);
    const y = (v: number) => H - PAD.b - ((v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);
    const idx = new Map(s.map((d, i) => [d[0], i]));
    const path = s.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[1]).toFixed(1)}`).join("");
    const bands = idea.trades.map((tr) => {
      const a = idx.get(tr.in) ?? 0;
      const b = idx.get(tr.out) ?? a;
      return { x0: x(a), x1: x(b), py: y(s[a][1]) };
    });
    const years: { x: number; label: string }[] = [];
    s.forEach((d, i) => {
      const yr = d[0].slice(0, 4);
      if (!years.length || years[years.length - 1].label !== yr) years.push({ x: x(i), label: yr });
    });
    return { path, bands, years };
  }, [idea]);

  const maxBar = Math.max(Math.abs(r.avg), Math.abs(r.randomMonth), 0.001);
  const v = verdict(idea);
  const toggle = (i: number) => setHover((h) => (h === i ? null : i));
  const show = { opacity: resP >= 1 ? 1 : 0 };

  return (
    <div className="studio" onPointerDown={done ? undefined : skip}>
      <div className="ask">
        <span className="ask-icon"><Icon name="spark" /></span>
        <span className="ask-text">
          {typed}
          {!done && t < T_STEPS && <span className="caret" />}
        </span>
        <span className={`ask-run ${done ? "ok" : step >= 0 ? "busy" : ""}`} aria-hidden>
          {done ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M5 12l5 5L20 7" /></svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          )}
        </span>
      </div>

      <div className="try" role="group" aria-label="Example ideas">
        {IDEAS.map((i) => (
          <button key={i.key} aria-pressed={i.key === key} className="try-chip" onClick={() => pick(i.key)} type="button">
            <Icon name={i.icon} /> {i.title}
            <span className={`chip-dot d-${verdict(i).cls}`} title={verdict(i).text} />
          </button>
        ))}
      </div>

      <div className="agent" aria-live="polite">
        {done ? (
          <span className="agent-done">
            <span className="tick">✓</span>
            {`Tested ${n} ${triggerWord(idea, n)} against real ${idea.label} prices, with your broker's fees`}
          </span>
        ) : (
          STEPS.map((s, i) => (
            <span key={s} className={`agent-step ${i < step ? "done" : i === step ? "now" : ""}`}>
              {i < step ? "✓" : i === step ? <span className="spin" /> : "·"} {s}
            </span>
          ))
        )}
      </div>

      <div className="studio-body">
        <div className="scan">
          <div className="scan-head">
            <span>{idea.spike ? "News spikes" : "Headlines"}</span>
            <span className="scan-count">{cards}</span>
          </div>
          <div className="scan-list">
            {idea.trades.slice(0, cards).map((tr, i) => (
              <div
                key={idea.key + tr.news + tr.name}
                className={`news ${hover === i ? "on" : ""}`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onClick={() => toggle(i)}
              >
                <div className="news-main">
                  <span className="news-date">
                    {fmtDate(tr.news)}
                    {tr.note && <span className="news-note"> · {tr.note}</span>}
                  </span>
                  <span className="news-title">{tr.name}</span>
                </div>
                <span className={`news-res ${r.net[i] > 0 ? "up" : "dn"}`} style={{ opacity: resP > 0 ? 1 : 0 }}>
                  {pct(r.net[i])}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="result">
          <div className="res-top">
            <div>
              <div className="res-label">Average return, {holdWords(idea.hold_days)} after each {triggerWord(idea, 1)}</div>
              <div className={`res-big ${r.avg >= 0 ? "up" : "dn"}`}>{resP > 0 ? pct(r.avg * ease) : "—"}</div>
            </div>
            <div className={`res-verdict v-${v.cls}`} style={show}>{v.text}</div>
          </div>

          <div className="compare" style={{ opacity: resP > 0 ? 1 : 0 }}>
            <div className="cmp-row">
              <span className="cmp-name">On the news</span>
              <span className="cmp-track"><i className="iris-bar" style={{ width: `${(Math.max(0, r.avg) / maxBar) * 100 * ease}%` }} /></span>
              <span className="cmp-val">{pct(r.avg)}</span>
            </div>
            <div className="cmp-row">
              <span className="cmp-name">{randomWords(idea.hold_days)}</span>
              <span className="cmp-track"><i style={{ width: `${(Math.max(0, r.randomMonth) / maxBar) * 100 * ease}%` }} /></span>
              <span className="cmp-val">{pct(r.randomMonth)}</span>
            </div>
          </div>

          <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${idea.label} price with each ${holdWords(idea.hold_days)} hold`}>
            <defs>
              <clipPath id="studio-clip">
                <rect x="0" y="0" height={H} width={W * chartP} />
              </clipPath>
            </defs>
            {chart.years.map((y) => (
              <text key={y.label} className="yr" x={y.x + 2} y={H - 4}>{y.label}</text>
            ))}
            <g clipPath="url(#studio-clip)">
              {chart.bands.map((b, i) => (
                <rect
                  key={i}
                  x={b.x0}
                  y={PAD.t}
                  width={Math.max(2, b.x1 - b.x0)}
                  height={H - PAD.t - PAD.b}
                  className={`band ${r.net[i] > 0 ? "b-up" : "b-dn"} ${hover === i ? "on" : ""}`}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => toggle(i)}
                />
              ))}
              <path className="line" d={chart.path} />
              {chart.bands.map((b, i) => (
                <circle key={i} cx={b.x0} cy={b.py} r={hover === i ? 6 : n > 20 ? 3 : 4} className="pin" />
              ))}
            </g>
          </svg>

          <div className="trio" style={show}>
            <div className="trio-cell">
              <div className="trio-l">Made money</div>
              <div className="trio-v">
                {r.wins}<span className="of"> of {n}</span>
              </div>
              <div className="dots" aria-hidden>
                {r.net.map((x, i) => (
                  <i key={i} className={x > 0 ? "w" : "l"} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
                ))}
              </div>
            </div>
            <div className="trio-cell">
              <div className="trio-l">Better than random dates</div>
              <div className="trio-v">{Math.round(idea.beats_random * 100)}%</div>
              <div className="meter" aria-hidden><i style={{ width: `${idea.beats_random * 100}%` }} /></div>
            </div>
            <div className="trio-cell">
              <div className="trio-l">$1,000 each time</div>
              <div className={`trio-v ${r.profitOn1k >= 0 ? "up" : "dn"}`}>{money(r.profitOn1k)}</div>
            </div>
          </div>

          <div className="fees" style={show}>
            <span className="fees-label">Fees from</span>
            <div className="seg" role="radiogroup" aria-label="Broker">
              {plats.map((p) => (
                <button key={p.id} role="radio" aria-checked={p.id === plat.id} title={p.why} onClick={() => setPlatId(p.id)} type="button">
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
