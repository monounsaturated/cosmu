// intent: typed access to the landing-page ideas (lib/showcase.json, built from real closes by
//   scripts/landing/build_showcase.py) + the broker cost models the visitor can switch between.
//   Never hand-edit the JSON; never invent a number.

import raw from "./showcase.json";

export type Trade = { news: string; name: string; note?: string; in: string; out: string; gross: number };
export type Idea = {
  key: string;
  title: string;
  icon: string;
  q: string;
  ask: string; // the plain-English question shown in the prompt bar
  asset: string;
  label: string;
  crypto: boolean;
  hold_days: number; // trading sessions held after each trigger
  spike: boolean; // true = triggers are detected news-volume spikes, false = hand-listed events
  random_month: number; // gross average return over the same hold, on random entry days
  beats_random: number;
  trades: Trade[];
  series: [string, number][];
};

export type Tested = { key: string; q: string; n: number; hold_days: number; avg: number; random: number; beats: number; pass: boolean; promising: boolean };

const DATA = raw as unknown as { ideas: Idea[]; tested: Tested[]; rule: { min_n: number; pass: number; promising: number } };
export const IDEAS = DATA.ideas;
export const TESTED = DATA.tested;
export const RULE = DATA.rule;

// One verdict rule for the whole page (same thresholds as scripts/landing/build_showcase.py).
export type Verdict = { cls: "strong" | "edge" | "rare" | "luck"; text: string };
export function verdict(idea: Idea): Verdict {
  const n = idea.trades.length;
  const b = idea.beats_random;
  if (n >= RULE.min_n && b >= RULE.pass) return { cls: "strong", text: "Passes the luck test" };
  if (n >= RULE.min_n && b >= RULE.promising) return { cls: "edge", text: "Promising edge" };
  if (n < RULE.min_n && b >= 0.9) return { cls: "rare", text: "Big but rare" };
  return { cls: "luck", text: "Fakeout · no edge" };
}

// Round-trip cost of a $1,000 buy + sell, as a fraction. Published retail schedules (2025), rounded.
export type Platform = { id: string; name: string; roundTrip: number; why: string };

export const STOCK_PLATFORMS: Platform[] = [
  { id: "ibkr", name: "Interactive Brokers", roundTrip: 0.0013, why: "$0.35 per order + a tight spread" },
  { id: "tr", name: "Trade Republic", roundTrip: 0.004, why: "€1 per order + exchange spread" },
  { id: "degiro", name: "DEGIRO", roundTrip: 0.0102, why: "€2 per US trade + 0.25% currency fee each way" },
  { id: "xtb", name: "XTB", roundTrip: 0.011, why: "no commission, 0.5% currency conversion each way" },
];

export const CRYPTO_PLATFORMS: Platform[] = [
  { id: "binance", name: "Binance", roundTrip: 0.003, why: "0.10% fee each way + spread" },
  { id: "kraken", name: "Kraken Pro", roundTrip: 0.009, why: "0.40% taker fee each way + spread" },
  { id: "revolut", name: "Revolut", roundTrip: 0.031, why: "about 1.5% fee each way on the standard plan" },
];

export const platformsFor = (idea: Idea) => (idea.crypto ? CRYPTO_PLATFORMS : STOCK_PLATFORMS);

export function results(idea: Idea, p: Platform) {
  const net = idea.trades.map((t) => t.gross - p.roundTrip);
  const avg = net.reduce((a, b) => a + b, 0) / net.length;
  const wins = net.filter((r) => r > 0).length; // same rule as the green dots
  const randomMonth = idea.random_month - p.roundTrip;
  return { net, avg, wins, randomMonth, profitOn1k: net.reduce((a, b) => a + b, 0) * 1000 };
}

// Trading sessions → plain words.
export const holdWords = (h: number) => (h <= 5 ? "1 week" : h <= 10 ? "2 weeks" : "1 month");
export const randomWords = (h: number) => (h <= 5 ? "Any random week" : h <= 10 ? "Any random 2 weeks" : "Any random month");
export const triggerWord = (idea: Idea, n = 2) => (idea.spike ? (n === 1 ? "news spike" : "news spikes") : n === 1 ? "headline" : "headlines");

export const pct = (x: number, digits = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`;
export const money = (x: number) => `${x >= 0 ? "+" : "−"}$${Math.round(Math.abs(x)).toLocaleString("en-US")}`;
export const fmtDate = (d: string) =>
  new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
