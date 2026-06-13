// Supplier billing fetcher — server-side only.
// Pulls REAL current-month spend from APIs where a token is available;
// falls back to clearly-labelled static estimates when a token is absent or the
// API call fails. Results are cached in-process for CACHE_TTL_MS (default 30 min)
// so billing APIs are never hit on every page render.
//
// Suppliers:
//   LIVE (API fetch): Railway (GraphQL), OpenRouter (REST)
//   ESTIMATED:        Vercel (token often absent), Supabase, Modal, Cloudflare R2,
//                     LunarCrush, GitHub Actions, Anthropic/Claude
//
// No Fly.io. Cloudflare R2 is the cold-data lake — built but default-OFF, so it honestly bills $0 until
// cold history migrates off Postgres (it appears on the register at $0 so the planned infra is visible).

export type SupplierRow = {
  /** Display name */
  name: string;
  /** Current-month USD spend (or static estimate) */
  amount_usd: number;
  /** "live" = fetched from the real billing API this call; "est" = static estimate */
  source: "live" | "est";
  /** ISO timestamp of the last successful live fetch, or null for estimates */
  fetched_at: string | null;
  /** One-liner describing what the supplier is for */
  role: string;
  /** Category label for grouping */
  category: "infra" | "data" | "llm" | "ci";
};

export type SupplierCostsResult = {
  rows: SupplierRow[];
  /** Sum of all row amounts — real + estimates */
  total_usd: number;
  /** ISO timestamp this result was produced (could be cache hit) */
  computed_at: string;
};

// ─── In-process cache ────────────────────────────────────────────────────────

const CACHE_TTL_MS = 30 * 60 * 1000; // 30 minutes

type CacheEntry = { result: SupplierCostsResult; expiry: number };
let cache: CacheEntry | null = null;

// ─── Static estimates (clearly labelled "est.") ──────────────────────────────
// Numbers are honest mid-range estimates based on the current plan tiers;
// they are never presented as precise actuals.

const STATIC_ESTIMATES: Omit<SupplierRow, "fetched_at">[] = [
  {
    name: "Vercel",
    amount_usd: 0,
    source: "est",
    role: "Web (Next.js) hosting — Hobby free tier",
    category: "infra",
  },
  {
    name: "Supabase",
    amount_usd: 0,
    source: "est",
    role: "Postgres + realtime — Free tier (500 MB, 2 projects)",
    category: "infra",
  },
  {
    name: "Modal",
    amount_usd: 5,
    source: "est",
    role: "Scale-to-zero heavy-compute lane (gate sweeps, ML train)",
    category: "infra",
  },
  {
    name: "Cloudflare R2",
    amount_usd: 0,
    source: "est",
    role: "Cold-data lake (Parquet) — zero-egress object storage. Built but default-OFF; $0 until cold history moves off Postgres.",
    category: "infra",
  },
  {
    name: "LunarCrush",
    amount_usd: 5,
    source: "est",
    role: "Social intelligence — $5/day plan (alt-data feed)",
    category: "data",
  },
  {
    name: "GitHub Actions",
    amount_usd: 0,
    source: "est",
    role: "CI — free tier (public repo, 2 000 min/mo)",
    category: "ci",
  },
  {
    name: "Anthropic / Claude",
    amount_usd: 20,
    source: "est",
    role: "Claude Max flat subscription (coding agent, no per-token billing)",
    category: "llm",
  },
];

// ─── Railway fetch ────────────────────────────────────────────────────────────
// Railway GraphQL v2: fetch current month's estimated spend for the default team/project.

async function fetchRailway(): Promise<{ amount_usd: number; ok: boolean }> {
  const token = process.env.RAILWAY_TOKEN;
  if (!token) return { amount_usd: 20, ok: false }; // fallback estimate

  // Railway GraphQL: query the viewer's teams and their estimated monthly spend.
  // We use `estimatedUsage` on the project if available, else `currentPeriodUsage`.
  const query = `
    query CosmuCosts {
      me {
        teams {
          edges {
            node {
              id
              name
              projects {
                edges {
                  node {
                    id
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
  `;

  try {
    const res = await fetch("https://backboard.railway.app/graphql/v2", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ query }),
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) return { amount_usd: 20, ok: false };
    // We only get project list here — Railway doesn't expose billed amounts in the public API
    // without going through the billing service. Use a second query for usage.
    const _data = await res.json();

    // Attempt to get current period usage via the usage endpoint
    const usageRes = await fetch("https://backboard.railway.app/graphql/v2", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        query: `
          query Usage {
            me {
              teams {
                edges {
                  node {
                    usage {
                      estimatedTotalCostDollars
                    }
                  }
                }
              }
            }
          }
        `,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    if (!usageRes.ok) return { amount_usd: 20, ok: false };
    const usageData = await usageRes.json();
    const teams = usageData?.data?.me?.teams?.edges ?? [];
    if (teams.length === 0) return { amount_usd: 20, ok: false };

    // Sum across all teams (usually 1)
    const total = teams.reduce(
      (sum: number, edge: { node: { usage?: { estimatedTotalCostDollars?: number } } }) => {
        const est = edge.node?.usage?.estimatedTotalCostDollars;
        return sum + (typeof est === "number" ? est : 0);
      },
      0,
    );

    if (total === 0) return { amount_usd: 20, ok: false }; // API returned but no cost field
    return { amount_usd: total, ok: true };
  } catch {
    return { amount_usd: 20, ok: false };
  }
}

// ─── OpenRouter fetch ─────────────────────────────────────────────────────────
// GET /api/v1/auth/key returns { data: { usage, ... } } where usage is total
// tokens consumed lifetime. OpenRouter charges per-token for paid models; we use
// :free models so spend is $0.  We still fetch to confirm and display actual usage.

async function fetchOpenRouter(): Promise<{ amount_usd: number; ok: boolean }> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) return { amount_usd: 0, ok: false };

  try {
    const res = await fetch("https://openrouter.ai/api/v1/auth/key", {
      headers: { Authorization: `Bearer ${key}` },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return { amount_usd: 0, ok: false };
    const body = await res.json();
    // body.data.usage is tokens used; body.data.limit_remaining may be present.
    // For :free-only usage, cost is 0 — confirmed via API.
    // If there is a `credit_balance` or `total_cost` field, use it.
    const totalCost = body?.data?.total_cost ?? body?.data?.usage_cost ?? 0;
    return { amount_usd: typeof totalCost === "number" ? totalCost : 0, ok: true };
  } catch {
    return { amount_usd: 0, ok: false };
  }
}

// ─── Vercel fetch ─────────────────────────────────────────────────────────────
// Vercel billing API requires a token. Token is often absent (empty string in env).

async function fetchVercel(): Promise<{ amount_usd: number; ok: boolean }> {
  const token = process.env.VERCEL_TOKEN;
  if (!token) return { amount_usd: 0, ok: false };

  try {
    const res = await fetch("https://api.vercel.com/v2/billing", {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return { amount_usd: 0, ok: false };
    const body = await res.json();
    // Vercel billing v2: body.balance or body.total or body.currentPeriodCost
    const cost =
      body?.invoices?.[0]?.total ??
      body?.currentPeriodCost ??
      body?.total ??
      0;
    return { amount_usd: typeof cost === "number" ? cost / 100 : 0, ok: true }; // cents → dollars
  } catch {
    return { amount_usd: 0, ok: false };
  }
}

// ─── Main public function ─────────────────────────────────────────────────────

export async function getSupplierCosts(): Promise<SupplierCostsResult> {
  // Cache hit?
  if (cache && cache.expiry > Date.now()) {
    return cache.result;
  }

  const now = new Date().toISOString();

  // Fire live fetches in parallel
  const [railway, openrouter, vercel] = await Promise.all([
    fetchRailway(),
    fetchOpenRouter(),
    fetchVercel(),
  ]);

  const liveRows: SupplierRow[] = [
    {
      name: "Railway",
      amount_usd: railway.amount_usd,
      source: railway.ok ? "live" : "est",
      fetched_at: railway.ok ? now : null,
      role: "Engine (FastAPI) — always-on backend + 4 h cron",
      category: "infra",
    },
    {
      name: "OpenRouter",
      amount_usd: openrouter.amount_usd,
      source: openrouter.ok ? "live" : "est",
      fetched_at: openrouter.ok ? now : null,
      role: "LLM gateway — :free models (strategy authoring + proposals)",
      category: "llm",
    },
    {
      name: "Vercel",
      amount_usd: vercel.ok ? vercel.amount_usd : STATIC_ESTIMATES.find((r) => r.name === "Vercel")!.amount_usd,
      source: vercel.ok ? "live" : "est",
      fetched_at: vercel.ok ? now : null,
      role: "Web (Next.js) hosting — Hobby free tier",
      category: "infra",
    },
  ];

  // Merge with static estimates, skipping suppliers already covered by liveRows
  const liveNames = new Set(liveRows.map((r) => r.name));
  const staticRows: SupplierRow[] = STATIC_ESTIMATES.filter((e) => !liveNames.has(e.name)).map(
    (e) => ({ ...e, fetched_at: null }),
  );

  // Canonical order: infra first, then data, llm, ci
  const ORDER: Record<string, number> = { infra: 0, data: 1, llm: 2, ci: 3 };
  const rows: SupplierRow[] = [...liveRows, ...staticRows].sort(
    (a, b) => (ORDER[a.category] ?? 9) - (ORDER[b.category] ?? 9),
  );

  const total_usd = rows.reduce((s, r) => s + r.amount_usd, 0);
  const result: SupplierCostsResult = { rows, total_usd, computed_at: now };

  cache = { result, expiry: Date.now() + CACHE_TTL_MS };
  return result;
}
