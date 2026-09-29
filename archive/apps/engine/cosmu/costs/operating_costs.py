# intent: SINGLE SOURCE OF TRUTH for Cosmu's OPERATING costs — the monthly cost of running the
# machine, net of which the only metric is profit. One file the operator updates on "go" from the
# cost spreadsheet (Wise card charges, Cosmu-attributed). Consumed by the infra seed (writer.py)
# and the constant vendor fetchers (fetchers.py) so a number is NEVER defined in two places.
#
# WHY no billing API: these are flat, known subscriptions — Claude Max, Cursor, etc. have no
# self-spend billing API at all; the usage-metered vendors that DO (OpenRouter, xAI, Railway,
# Modal) run ~$0 here (free Claude-Code sub, rotating Modal credits) and are fetched live
# elsewhere; and the one useful automation — reconciling actual card charges from Wise — is
# blocked for an EU/France personal account by PSD2. So: the operator updates, the machine
# records. See docs + memory "cost-tracking-standard".
#
# CURRENCY: amounts are USD — the app is USD-native (equity / P&L are USD/USDT on Binance, and
# opex_vs_alpha = total_usd / equity). The operator pays in EUR; EUR_PER_USD records the real
# card-charge reality in human-facing notes. Refresh the rate and amounts when the sheet changes;
# everything downstream re-derives.

from __future__ import annotations

# FX snapshot (mid-June 2026, exchange-rates.org). USD stays the canonical unit; this only
# annotates EUR-paid reality. Refresh when it drifts materially.
EUR_PER_USD: float = 0.86   # 1 USD ≈ 0.86 EUR
USD_PER_EUR: float = 1.16   # 1 EUR ≈ 1.16 USD


def to_eur(usd: float) -> float:
    """USD → EUR at the recorded snapshot rate (human-facing notes only)."""
    return round(usd * EUR_PER_USD, 2)


def to_usd(eur: float) -> float:
    """EUR card charge → USD at the recorded snapshot rate."""
    return round(eur * USD_PER_EUR, 2)


# Category vocabulary. 'marketing' = partnerships / networking (e.g. a drink with a finance
# contact) — booked as a real one-shot cost, never a subscription.
CAT_INFRA = "infra"
CAT_DATA = "data"
CAT_LLM = "llm"
CAT_MARKETING = "marketing"


# ── Recurring infra + data lines (flat / known monthly) ──────────────────────────────────────
# Seeded once per calendar month into the costs table (writer.seed_infra_costs). The recorded
# amount is the midpoint of [min, max]; free tiers are min == max == 0. These are plan-tier
# estimates — NOT live billing. The usage-metered ones (Railway, Modal) are overridden by the
# live fetch in the register; Claude/Cursor are NOT here (they are flat subs owned by the
# fetchers — see FLAT_SUBSCRIPTIONS — so each is counted exactly once).
INFRA_DATA_LINES: list[dict] = [
    {"vendor": "Railway",    "category": CAT_INFRA, "amount_min": 5.0, "amount_max": 10.0, "note": "always-on engine API + crons (EU west) — usage-metered, live-fetched"},
    {"vendor": "Supabase",   "category": CAT_INFRA, "amount_min": 0.0, "amount_max": 0.0,  "note": "Postgres — Pro CANCELED 2026-06, back on Free ($0; 282 MB < 500 MB cap)"},
    {"vendor": "Vercel",     "category": CAT_INFRA, "amount_min": 0.0, "amount_max": 0.0,  "note": "web (Next.js) — Hobby free"},
    {"vendor": "Modal",      "category": CAT_INFRA, "amount_min": 0.0, "amount_max": 10.0, "note": "bursty heavy compute — rotating free credits (~$0 net), scale-to-zero idle"},
    {"vendor": "FRED",       "category": CAT_DATA,  "amount_min": 0.0, "amount_max": 0.0,  "note": "macro — free"},
    {"vendor": "GDELT",      "category": CAT_DATA,  "amount_min": 0.0, "amount_max": 0.0,  "note": "news — free"},
    {"vendor": "Polymarket", "category": CAT_DATA,  "amount_min": 0.0, "amount_max": 0.0,  "note": "prediction markets — free"},
    {"vendor": "LunarCrush", "category": CAT_DATA,  "amount_min": 0.0, "amount_max": 0.0,  "note": "social signals — one-shot/usage only; no active sub as of 2026-06"},
]


# ── Flat LLM / dev subscriptions (constant monthly, no billing API) ──────────────────────────
# Owned by the constant vendor-fetchers (fetchers.py), NOT the infra seed, so each is counted
# exactly once. amount is a flat USD/mo. These are the operator's real recurring tools and the
# bulk of opex — getting them right is what makes the "profit, net of costs" metric honest.
FLAT_SUBSCRIPTIONS: list[dict] = [
    {"vendor": "Claude", "category": CAT_LLM, "amount": 200.0, "note": "Claude Max 20x — flat sub (~€172/mo); strategy authoring runs here, not the paid API"},
    {"vendor": "Cursor", "category": CAT_LLM, "amount": 20.0,  "note": "Cursor Pro — AI coding IDE (~€17/mo)"},
]


def flat_subscription(vendor: str) -> dict | None:
    """Return the flat-subscription line for a vendor, or None if it isn't one."""
    for sub in FLAT_SUBSCRIPTIONS:
        if sub["vendor"] == vendor:
            return sub
    return None


# ── Recent one-shot / usage spend (NOT recurring) ────────────────────────────────────────────
# Recorded for the historical total but EXCLUDED from the steady-state run-rate (they don't
# recur). Appended each month from the cost sheet. `eur` is the real card charge; USD is derived.
# This is the canonical record for "Verre = marketing/partnerships" and the variable LLM/data
# top-ups the operator flagged as one-shots.
ONE_SHOTS: list[dict] = [
    {"period": "2026-06", "vendor": "OpenRouter",          "category": CAT_LLM,       "eur": 10.88, "note": "LLM gateway credit top-up — usage"},
    {"period": "2026-06", "vendor": "LunarCrush",          "category": CAT_DATA,      "eur": 4.51,  "note": "social data — one-shot"},
    {"period": "2026-04", "vendor": "xAI",                 "category": CAT_LLM,       "eur": 8.56,  "note": "Grok API credits (15/04 + 25/04) — usage"},
    {"period": "2026-05", "vendor": "Verre Alex Finance",  "category": CAT_MARKETING, "eur": 12.50, "note": "partnerships / networking — finance contact"},
]


# ── Convenience: steady-state recurring run-rate ─────────────────────────────────────────────
def monthly_run_rate_usd() -> float:
    """Best-estimate steady-state recurring opex (USD/mo): flat subs + infra/data midpoints.
    Excludes one-shots and floating usage-metered spend. Informational — not a gate input.

    As of 2026-06: Claude Max 20x ($200) + Cursor ($20) + Railway (~$7.5 mid) ≈ $227.5/mo
    (≈ €196), in line with the operator's stated ~€200/mo."""
    flat = sum(s["amount"] for s in FLAT_SUBSCRIPTIONS)
    infra = sum((line["amount_min"] + line["amount_max"]) / 2.0 for line in INFRA_DATA_LINES)
    return round(flat + infra, 2)
