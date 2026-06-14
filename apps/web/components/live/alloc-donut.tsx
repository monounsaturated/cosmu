// Live capital-allocation donut — where the LIVE account's deployed capital sits, per venue. Shows venue
// NAME + amount only (no free cash, no asset class). Honest empty when nothing is deployed live. Sits in
// the KPI row at 2/8 width. Fed from GET /live/venues (deployed_usd per venue).

import { formatUsd } from "@/lib/utils";

const PALETTE = ["var(--gold)", "var(--info)", "var(--up)", "var(--iris)", "var(--down)"];

export function AllocDonut({ venues }: { venues: { name: string; amount: number }[] }) {
  const items = venues.filter((v) => v.amount > 0);
  const total = items.reduce((s, v) => s + v.amount, 0);

  if (total <= 0) {
    return (
      <div className="kpi-box alloc-box">
        <div className="alloc-empty">No live capital deployed</div>
      </div>
    );
  }

  let cum = 0;
  const segs = items.map((v, i) => {
    const pct = (v.amount / total) * 100;
    const seg = { color: PALETTE[i % PALETTE.length], pct, offset: -cum, name: v.name, amount: v.amount };
    cum += pct;
    return seg;
  });

  return (
    <div className="kpi-box alloc-box">
      <svg className="donut" width="46" height="46" viewBox="0 0 36 36" aria-label="Capital by venue">
        <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--surf3)" strokeWidth="4" />
        {segs.map((s) => (
          <circle
            key={s.name}
            cx="18"
            cy="18"
            r="15.9155"
            fill="none"
            stroke={s.color}
            strokeWidth="4"
            strokeDasharray={`${s.pct} ${100 - s.pct}`}
            strokeDashoffset={s.offset}
            transform="rotate(-90 18 18)"
          />
        ))}
      </svg>
      <div className="alloc-leg">
        {segs.map((s) => (
          <div className="arow" key={s.name}>
            <span className="alloc-dot" style={{ background: s.color }} />
            <span className="nm">{s.name}</span>
            <span className="amt">{formatUsd(s.amount)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
