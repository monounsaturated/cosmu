// Cost register — the SINGLE source of truth for the Costs page.
//
// Every line below is a real, operator-known spend (reconciled against the provider invoices /
// the billing sheet). There is no live billing API fetch and no per-browser override layer: the costs
// are maintained HERE, in code (edited by Claude Code), so the page is a faithful, read-only mirror of
// what is actually being spent.
//
// CURRENCY: each amount is stored in its NATIVE currency — `{ eur }` for the (mostly EUR) provider
// invoices, `{ usd }` for the lines already known in USD (Claude Max plan, GitHub Actions metered usage).
// The page displays USD: `buildCostLines(rate)` converts every EUR amount with the LIVE daily EUR→USD
// rate (see app/data/fx.ts), so the figures re-rate every day instead of being frozen at a constant.
//
// Each line carries the facts the UI shows: whether it is currently `recurring`, the recurring `monthly`
// price (the estimates derive from these), real `lifetime` spend, and the renewal calendar (`lastPaid` /
// `renews`). Cancelled / free / usage / one-off lines are `recurring: false` so their estimates are $0.

// The four tile buckets are infra · trading · data · ai. "other" is the catch-all (e.g. partnerships)
// that has no tile — it surfaces in the "Other" headline box instead and renders without a badge.
export type CostCat = "infra" | "data" | "ai" | "trading" | "other";

// A native-currency amount. EUR amounts re-rate daily; USD amounts pass through unchanged.
export type Money = { eur: number } | { usd: number };

// Fallback EUR→USD used when the live rate is unavailable (and for the static COST_LINES export).
export const FALLBACK_EUR_USD = 1.08;

const toUsd = (m: Money, rate: number) => ("usd" in m ? m.usd : m.eur * rate);

// The display shape (USD) consumed by the page + components.
export type CostLine = {
  source: string;
  category: CostCat;
  /** Is the source CURRENTLY billed on a recurring basis? (false = cancelled / free / usage / one-off). */
  recurring: boolean;
  /** Estimated USD/mo — the recurring price when `recurring`, else 0. */
  estMo: number;
  /** Estimated USD/yr — estMo × 12. */
  estYr: number;
  /** Real USD spent to date. */
  lifetime: number;
  lastPaid: string | null;
  renews: string | null;
};

// The raw register (native currency). `monthly` is the recurring price; the estimates derive from it and
// the `recurring` flag. Ordered infra → data → ai → other.
type RawCostLine = {
  source: string;
  category: CostCat;
  recurring: boolean;
  monthly: Money;
  lifetime: Money;
  lastPaid: string | null;
  renews: string | null;
};

const Z: Money = { usd: 0 };

const RAW_COST_LINES: RawCostLine[] = [
  // ── INFRA ──
  { source: "Railway", category: "infra", recurring: true, monthly: { eur: 4.37 }, lifetime: { eur: 4.37 + 4.3 }, lastPaid: "2026-05-17", renews: "2026-07-17" },
  { source: "Vercel", category: "infra", recurring: false, monthly: Z, lifetime: Z, lastPaid: null, renews: null },
  { source: "Supabase", category: "infra", recurring: false, monthly: Z, lifetime: { eur: 22.05 }, lastPaid: "2026-06-06", renews: null },
  { source: "Modal", category: "infra", recurring: false, monthly: Z, lifetime: Z, lastPaid: null, renews: null },
  { source: "Cloudflare R2", category: "infra", recurring: false, monthly: Z, lifetime: Z, lastPaid: null, renews: null },
  { source: "GitHub Actions", category: "infra", recurring: false, monthly: Z, lifetime: { usd: 4.96 }, lastPaid: null, renews: null },

  // ── DATA ──
  { source: "LunarCrush", category: "data", recurring: false, monthly: Z, lifetime: { eur: 4.51 }, lastPaid: "2026-06-05", renews: null },

  // ── AI / LLM ──
  // Claude Max plan: $200/mo + 20% French VAT (USD-native). Renews 30 days after the last payment.
  { source: "Anthropic / Claude", category: "ai", recurring: true, monthly: { usd: Math.round(200 * 1.2) }, lifetime: { eur: 127.85 + 88.25 + 21.6 + 21.6 }, lastPaid: "2026-06-06", renews: "2026-07-06" },
  // Cursor Pro cancelled — no longer recurring.
  { source: "Cursor", category: "ai", recurring: false, monthly: Z, lifetime: { eur: 21.53 + 10.77 }, lastPaid: "2026-05-01", renews: null },
  { source: "OpenRouter", category: "ai", recurring: false, monthly: Z, lifetime: { eur: 10.88 }, lastPaid: "2026-06-01", renews: null },
  { source: "xAI", category: "ai", recurring: false, monthly: Z, lifetime: { eur: 4.29 + 4.27 }, lastPaid: "2026-04-25", renews: null },

  // ── OTHER (no tile / no badge) ──
  { source: "Partnerships", category: "other", recurring: false, monthly: Z, lifetime: { eur: 12.5 }, lastPaid: "2026-05-25", renews: null },
];

// Convert the raw register to USD display lines at the given EUR→USD rate. The estimates derive purely
// from the recurring flag + the recurring amount: est/mo = recurring ? monthly : 0, est/yr = est/mo × 12.
export function buildCostLines(eurUsd: number = FALLBACK_EUR_USD): CostLine[] {
  return RAW_COST_LINES.map((l) => {
    const estMo = l.recurring ? toUsd(l.monthly, eurUsd) : 0;
    return {
      source: l.source,
      category: l.category,
      recurring: l.recurring,
      estMo,
      estYr: estMo * 12,
      lifetime: toUsd(l.lifetime, eurUsd),
      lastPaid: l.lastPaid,
      renews: l.renews,
    };
  });
}

// Static fallback-rate lines (used as the costTotals default; the page passes live-rated lines instead).
export const COST_LINES: CostLine[] = buildCostLines();

export type CostTotals = {
  /** Σ lifetime — total spent to date (USD). */
  totalSpend: number;
  /** Σ perMo — recurring monthly run-rate (USD). */
  runRate: number;
  /** Σ lifetime for the catch-all "other" category (the "Other" headline box). */
  otherSpend: number;
  /** Lifetime $ per tile bucket, in tile order (trading is 0 — no trading costs yet). */
  byCategory: { category: string; amount: number }[];
};

// Everything is displayed in whole dollars, so we round EACH line to a whole dollar BEFORE summing —
// that way the headline totals, the four tiles, the "Other" box and the table all reconcile exactly
// (no "sum-of-rounded ≠ rounded-sum" off-by-$1 artifacts).
export function costTotals(lines: CostLine[] = COST_LINES): CostTotals {
  const r = Math.round;
  const totalSpend = lines.reduce((s, l) => s + r(l.lifetime), 0);
  const runRate = lines.reduce((s, l) => s + r(l.estMo), 0);
  const otherSpend = lines.filter((l) => l.category === "other").reduce((s, l) => s + r(l.lifetime), 0);
  const buckets: Record<string, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const l of lines) if (l.category in buckets) buckets[l.category] += r(l.lifetime);
  const byCategory = (["infra", "trading", "data", "ai"] as const).map((category) => ({
    category,
    amount: buckets[category],
  }));
  return { totalSpend, runRate, otherSpend, byCategory };
}
