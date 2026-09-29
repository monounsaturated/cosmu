// intent: typed access to the ONE real demo dataset (CIBR × hack news, 2021–2025) + the per-platform cost
//   model the landing page applies in the browser. Data is produced offline by
//   scripts/landing/build_cibr_demo.py from real Yahoo closes — never hand-edited, never synthetic.

import raw from "./cibr-hacks.json";

export type HackEvent = {
  news: string; // day the story broke
  fill: string; // first session strictly after → the buy
  name: string;
  what: string;
  price: number;
  ret20: number; // 20-trading-day return after the buy
};

// [date, adjusted close, shares held, cumulative cost]
export type Point = [string, number, number, number];

export type Demo = {
  asset: string;
  asset_name: string;
  window: [string, string];
  rule: string;
  source: string;
  horizon_days: number;
  last_price: number;
  events: HackEvent[];
  stats: {
    trades: number;
    gross_multiple: number;
    avg_ret20_after_hack: number;
    avg_ret20_any_day: number;
    hit_rate_20d: number;
    random_median_multiple: number;
    pct_random_beaten: number;
  };
  series: Point[];
};

export const DEMO = raw as Demo;

export type Platform = {
  id: string;
  name: string;
  kind: string;
  commission: (price: number) => number; // USD per 1-share order
  fxBps: number; // currency conversion for a EUR account buying a USD ETF
  slipBps: number; // half-spread + market impact estimate
  carryPerYear: number; // overnight financing on a leveraged product (CFD), as a fraction of notional
  note: string;
};

// Published retail schedules (2025) for a 1-share US ETF market order. Rounded; verify with the broker.
export const PLATFORMS: Platform[] = [
  {
    id: "ibkr",
    name: "Interactive Brokers",
    kind: "Pro · Tiered",
    commission: (p) => Math.min(0.35, 0.01 * p), // $0.0035/share, $0.35 min, 1% of value cap
    fxBps: 0.2,
    slipBps: 3,
    carryPerYear: 0,
    note: "$0.35 minimum per order, near-interbank FX.",
  },
  {
    id: "t212",
    name: "Trading 212",
    kind: "Invest · EUR account",
    commission: () => 0,
    fxBps: 15,
    slipBps: 4,
    carryPerYear: 0,
    note: "Zero commission, 0.15% FX fee on every USD buy.",
  },
  {
    id: "degiro",
    name: "DEGIRO",
    kind: "Basic · EUR account",
    commission: () => 2.2,
    fxBps: 25,
    slipBps: 4,
    carryPerYear: 0,
    note: "€2 per US trade + 0.25% AutoFX, which is heavy on a $50 order.",
  },
  {
    id: "mt5",
    name: "MetaTrader 5",
    kind: "Stock CFD · typical broker",
    commission: () => 0,
    fxBps: 0,
    slipBps: 10,
    carryPerYear: 0.065, // ~benchmark rate + 2.5% broker markup, charged nightly on a long CFD
    note: "No commission, but a CFD pays ~6.5%/yr overnight financing. Holding it for years is expensive.",
  },
];

export type CostResult = { invested: number; fees: number; value: number; net: number; gross: number };

export function applyCosts(d: Demo, p: Platform): CostResult {
  let invested = 0;
  let fees = 0;
  const end = Date.parse(d.window[1]);
  for (const e of d.events) {
    const years = (end - Date.parse(e.fill)) / (365.25 * 864e5);
    invested += e.price;
    fees += p.commission(e.price) + e.price * ((p.fxBps + p.slipBps) / 10_000) + e.price * p.carryPerYear * years;
  }
  const value = d.events.length * d.last_price;
  return { invested, fees, value, gross: value / invested - 1, net: value / (invested + fees) - 1 };
}

export const pct = (x: number, digits = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`;
export const usd = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// SVG path helpers — plain math, no charting library.
export function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  return (v: number) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
}

export function linePath(xs: number[], ys: number[]) {
  return xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join("");
}
