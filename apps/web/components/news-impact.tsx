"use client";

// intent: feature 2 — how did each hack headline move the price? Real CIBR closes with every event pinned
//   on the date the buy could first happen, and each event's 20-trading-day reaction next to the
//   "any normal day" baseline. Click or arrow-key through events.

import { useMemo, useState } from "react";
import { DEMO, linePath, pct, scale } from "@/lib/demo";
import { useInView } from "./reveal";

const W = 1000;
const H = 220;
const PAD = { l: 52, r: 10, t: 16, b: 30 };
const RANGE = 0.1; // bars span −10% … +10%

export function NewsImpact() {
  const [sel, setSel] = useState(DEMO.events.findIndex((e) => e.name === "Colonial Pipeline"));
  const [ref, seen] = useInView<HTMLDivElement>(0.25);
  const ev = DEMO.events[sel];

  const chart = useMemo(() => {
    const s = DEMO.series;
    const prices = s.map((p) => p[1]);
    const lo = Math.floor(Math.min(...prices) / 10) * 10;
    const hi = Math.ceil(Math.max(...prices) / 10) * 10;
    const x = scale([0, s.length - 1], [PAD.l, W - PAD.r]);
    const y = scale([lo, hi], [H - PAD.b, PAD.t]);
    const xs = s.map((_, i) => x(i));
    const ys = prices.map(y);
    const idx = new Map(s.map((p, i) => [p[0], i]));
    const marks = DEMO.events.map((e) => {
      const i = idx.get(e.fill) ?? 0;
      return { x: xs[i], y: ys[i] };
    });
    const years: { x: number; label: string }[] = [];
    s.forEach((p, i) => {
      const yr = p[0].slice(0, 4);
      if (!years.length || years[years.length - 1].label !== yr) years.push({ x: xs[i], label: yr });
    });
    const ticks = [lo, (lo + hi) / 2, hi].map((v) => ({ y: y(v), label: `$${Math.round(v)}` }));
    return { path: linePath(xs, ys), marks, years, ticks };
  }, []);

  const barY = (v: number) => 50 - (v / RANGE) * 50; // % from top
  const base = DEMO.stats.avg_ret20_any_day;

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowRight") setSel((i) => Math.min(DEMO.events.length - 1, i + 1));
    if (e.key === "ArrowLeft") setSel((i) => Math.max(0, i - 1));
  }

  return (
    <div ref={ref} className="cell" onKeyDown={onKey}>
      <div className="impact-head">
        <div className="impact-pick" aria-live="polite">
          <div className="cell-label" style={{ marginBottom: 6 }}>
            <span className="mono">{ev.news}</span> · headline
          </div>
          <div className="n">{ev.name}</div>
          <div className="w">{ev.what}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="cell-label">CIBR, next 20 trading days</div>
          <div className={`big ${ev.ret20 >= 0 ? "up" : "dn"}`} style={{ fontSize: 40, marginTop: 6 }}>
            {pct(ev.ret20)}
          </div>
          <div className="quiet" style={{ fontSize: 12 }}>
            bought {ev.fill} at <span className="mono">${ev.price.toFixed(2)}</span>
          </div>
        </div>
      </div>

      <svg className="chart wide" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="CIBR price 2021 to 2025 with hack news marked">
        <g className="grid">
          {chart.ticks.map((k) => (
            <line key={k.label} x1={PAD.l} x2={W - PAD.r} y1={k.y} y2={k.y} />
          ))}
        </g>
        <g className="axis">
          {chart.ticks.map((k) => (
            <text key={k.label} x={PAD.l - 8} y={k.y + 3} textAnchor="end">{k.label}</text>
          ))}
          {chart.years.map((yr) => (
            <text key={yr.label} x={yr.x} y={H - 4}>{yr.label}</text>
          ))}
        </g>
        <path className={`value draw ${seen ? "go" : ""}`} pathLength={1} d={chart.path} style={{ strokeWidth: 1.8 }} />
        <line x1={chart.marks[sel].x} x2={chart.marks[sel].x} y1={PAD.t} y2={H - PAD.b} stroke="var(--gold)" strokeDasharray="3 3" opacity={0.6} />
        {chart.marks.map((m, i) => (
          <circle
            key={i}
            className={`mk pop ${seen ? "go" : ""}`}
            cx={m.x}
            cy={m.y}
            r={i === sel ? 6.5 : 4}
            style={{ animationDelay: `${600 + i * 60}ms`, cursor: "pointer" }}
            onClick={() => setSel(i)}
          >
            <title>{DEMO.events[i].name}</title>
          </circle>
        ))}
      </svg>

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 18, gap: 12, flexWrap: "wrap" }}>
        <div className="cell-label">20-day reaction, every event</div>
        <div className="legend">
          <span><i style={{ background: "var(--up)" }} />up</span>
          <span><i style={{ background: "var(--down)" }} />down</span>
          <span><i className="c" style={{ background: "repeating-linear-gradient(90deg,var(--gold) 0 4px,transparent 4px 8px)" }} />any normal day</span>
        </div>
      </div>
      <div className="bars" role="listbox" aria-label="Hack events" tabIndex={0}>
        <div className="zero" style={{ top: `${barY(0)}%` }} />
        {DEMO.events.map((e, i) => {
          const top = Math.min(barY(e.ret20), 50);
          const h = Math.abs(barY(e.ret20) - 50);
          return (
            <div
              key={i}
              role="option"
              aria-selected={i === sel}
              aria-label={`${e.name}: ${pct(e.ret20)}`}
              className={`bar ${i === sel ? "sel" : ""}`}
              onClick={() => setSel(i)}
              onMouseEnter={() => setSel(i)}
            >
              <i
                style={{
                  top: `${top}%`,
                  height: seen ? `${h}%` : 0,
                  background: e.ret20 >= 0 ? "var(--up)" : "var(--down)",
                  transition: `height 700ms cubic-bezier(0.16,1,0.3,1) ${i * 35}ms, filter 160ms`,
                }}
              />
            </div>
          );
        })}
        <div className="baseline" style={{ top: `${barY(base)}%` }}>
          <span>{pct(base, 2)}</span>
        </div>
      </div>
      <p className="quiet" style={{ fontSize: 12, marginTop: 14 }}>
        {Math.round(DEMO.stats.hit_rate_20d * 100)}% of events were followed by a rise, averaging{" "}
        <span className="mono">{pct(DEMO.stats.avg_ret20_after_hack, 2)}</span>. A random day gives{" "}
        <span className="mono">{pct(base, 2)}</span>. Hover or use ← → to explore.
      </p>
    </div>
  );
}
