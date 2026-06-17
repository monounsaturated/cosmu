// Cost register — the SINGLE source of truth for the Costs page.
//
// Every line below is a real, operator-known spend (reconciled against the provider invoices /
// the billing sheet). There is no live billing API fetch and no per-browser override layer any
// more: the costs are maintained HERE, in code (edited by Claude Code), so the page is a faithful,
// read-only mirror of what is actually being spent.
//
// CURRENCY: provider invoices are billed in EUR; the page displays USD. Amounts entered in EUR are
// converted once, here, through EUR_USD. Lines already known in USD (e.g. the Claude Max plan,
// GitHub Actions metered usage) are entered directly in USD — no conversion.
//
// Each line carries the facts the UI shows: monthly run-rate (`perMo`), lifetime-to-date
// (`lifetime`), the renewal calendar (`lastPaid` / `renews`), cadence and a one-liner. Free / $0
// services are kept (you still track when they renew), they simply contribute $0.

export type Cadence = "monthly" | "usage" | "oneoff";

export const CADENCE_LABEL: Record<Cadence, string> = {
  monthly: "monthly",
  usage: "usage",
  oneoff: "one-off",
};

// The four tile buckets are infra · trading · data · ai. "other" is the catch-all (e.g. partnerships)
// that has no tile — it surfaces in the "Other" headline box instead and renders without a badge.
export type CostCat = "infra" | "data" | "ai" | "trading" | "other";

export type CostLine = {
  /** Display name. */
  source: string;
  /** Category bucket (folds onto the four tiles; "trading" has no costs yet). */
  category: CostCat;
  cadence: Cadence;
  /** USD monthly run-rate. 0 for free / usage-metered / one-off lines. */
  perMo: number;
  /** USD spent to date. 0 when nothing has been billed yet. */
  lifetime: number;
  /** ISO date of the last payment, or null. */
  lastPaid: string | null;
  /** ISO date of the next renewal, or null (usage / one-off / free). */
  renews: string | null;
  /** One-line description. */
  note: string;
};

// EUR → USD. Provider invoices are in EUR; tweak this single constant to re-rate every EUR line.
const EUR_USD = 1.08;
const usd = (eur: number) => Math.round(eur * EUR_USD * 100) / 100;

// ─── The register (source of truth) ──────────────────────────────────────────────
// Ordered infra → data → ai. Dates are ISO; "renews" is the next due date for recurring lines.
export const COST_LINES: CostLine[] = [
  // ── INFRA ──
  {
    source: "Railway",
    category: "infra",
    cadence: "monthly",
    perMo: usd(4.37),
    lifetime: usd(4.37 + 4.3),
    lastPaid: "2026-05-17",
    renews: "2026-06-17",
    note: "Engine (FastAPI) backend + cron — europe-west4",
  },
  {
    source: "Vercel",
    category: "infra",
    cadence: "monthly",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Web (Next.js) hosting — Hobby free tier",
  },
  {
    source: "Supabase",
    category: "infra",
    cadence: "monthly",
    perMo: 0,
    lifetime: usd(22.05),
    lastPaid: "2026-06-06",
    renews: null,
    note: "Postgres — Pro cancelled, back on Free plan ($0)",
  },
  {
    source: "Modal",
    category: "infra",
    cadence: "monthly",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Scale-to-zero heavy-compute lane — free tier",
  },
  {
    source: "Cloudflare R2",
    category: "infra",
    cadence: "monthly",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Cold-data lake (Parquet) — zero-egress, $0",
  },
  {
    source: "GitHub Actions",
    category: "infra",
    cadence: "usage",
    perMo: 0,
    lifetime: 4.96,
    lastPaid: null,
    renews: null,
    note: "CI minutes — metered usage",
  },

  // ── DATA ──
  {
    source: "LunarCrush",
    category: "data",
    cadence: "oneoff",
    perMo: 0,
    lifetime: usd(4.51),
    lastPaid: "2026-06-05",
    renews: null,
    note: "Social intelligence — one-off",
  },
  {
    source: "FRED",
    category: "data",
    cadence: "usage",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Macro series (St. Louis Fed) — free",
  },
  {
    source: "Polymarket",
    category: "data",
    cadence: "usage",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Prediction-market odds — free",
  },
  {
    source: "GDELT",
    category: "data",
    cadence: "usage",
    perMo: 0,
    lifetime: 0,
    lastPaid: null,
    renews: null,
    note: "Global news/event tone — free",
  },

  // ── AI / LLM ──
  {
    source: "Anthropic / Claude",
    category: "ai",
    cadence: "monthly",
    // Claude Max plan: $200/mo + 20% French VAT. Renews 30 days after the last payment.
    perMo: Math.round(200 * 1.2),
    lifetime: usd(127.85 + 88.25 + 21.6 + 21.6),
    lastPaid: "2026-06-06",
    renews: "2026-07-06",
    note: "Claude Max — $200/mo + 20% FR VAT (coding agent)",
  },
  {
    source: "Cursor",
    category: "ai",
    cadence: "monthly",
    perMo: usd(21.53),
    lifetime: usd(21.53 + 10.77),
    lastPaid: "2026-05-01",
    renews: "2026-07-01",
    note: "Cursor Pro — editor agent",
  },
  {
    source: "OpenRouter",
    category: "ai",
    cadence: "usage",
    perMo: 0,
    lifetime: usd(10.88),
    lastPaid: "2026-06-01",
    renews: null,
    note: "LLM gateway — metered usage",
  },
  {
    source: "xAI",
    category: "ai",
    cadence: "usage",
    perMo: 0,
    lifetime: usd(4.29 + 4.27),
    lastPaid: "2026-04-25",
    renews: null,
    note: "Grok API credits — metered usage",
  },

  // ── OTHER (no tile / no badge) ──
  {
    source: "Partnerships",
    category: "other",
    cadence: "oneoff",
    perMo: 0,
    lifetime: usd(12.5),
    lastPaid: "2026-05-25",
    renews: null,
    note: "Business development — one-off",
  },
];

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
  const runRate = lines.reduce((s, l) => s + r(l.perMo), 0);
  const otherSpend = lines.filter((l) => l.category === "other").reduce((s, l) => s + r(l.lifetime), 0);
  const buckets: Record<string, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const l of lines) if (l.category in buckets) buckets[l.category] += r(l.lifetime);
  const byCategory = (["infra", "trading", "data", "ai"] as const).map((category) => ({
    category,
    amount: buckets[category],
  }));
  return { totalSpend, runRate, otherSpend, byCategory };
}
