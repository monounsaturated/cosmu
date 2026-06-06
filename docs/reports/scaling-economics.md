# COSMU — Scaling Economics: what costs grow, and the cheap-to-scale architecture

The honest headline: **infra scales CHEAPLY if you tier it right. The only costs that really grow are the AI dev
(Claude) and — eventually — trading capital.** Don't scale Postgres for cold data; don't buy a VPS.

## Cost by component — now vs scaled

| Component | Now | At scale | Cheap-to-scale move |
|---|---|---|---|
| **Postgres (Supabase)** | Pro $25 / 8 GB (~6 GB used) | DB grows with sources×coins×history | **HOT/COLD TIERING** ⬇️ — keep only hot (recent + traded universe) in PG (~$25 forever); archive the full history to object storage. Beyond 8 GB on PG ≈ $0.125/GB/mo — avoid by tiering. |
| **Cold data storage** | — (all in PG) | TBs of history | **Cloudflare R2: $0.015/GB/mo, $0 egress** → 1 TB ≈ **$15/mo**. (S3 = $0.023/GB + egress fees → R2 wins.) Store as **parquet**; backtests read it directly with **DuckDB/polars** (free, fast). |
| **Data sources (APIs)** | LunarCrush $5/day (cancelling); rest free | More feeds | **Free backbone** (Binance Vision, FRED, DefiLlama, GDELT, CoinGecko, Deribit). Paid feeds (Glassnode ~$30–100, LlamaParse ~usage) only behind a PROVEN edge. **One-shot grabs** (subscribe→grab→cancel) beat always-on. |
| **Compute (backtests/sweeps/ML)** | local Mac (free) + Modal (~$0 idle) | 10k-strategy sweeps, ML training | **Modal pay-per-use, scale-to-zero** — a big sweep ≈ a few $; GPU for ML ~$1–4/hr only while training. No idle cost. **No VPS** (idle cost + ops burden). |
| **Engine/web host (Railway/Vercel)** | ~$5–20 / ~$0 | live cron + traffic | Railway usage-based (~$20–50 at live-trading scale); Vercel hobby→$20. Modest. |
| **CI (GitHub Actions)** | ~$1–5/mo (PR-only + path-filtered, $10 cap) | more PRs | Already lean + off-Mac. Don't self-host (burdens Mac), don't Codespaces (paid VM). |
| **Claude (AI dev/analyst)** | 5x ~$100 → 20x ~$200 | THE variable cost | **Scale UP during build sprints, DOWN (5x) in steady-state** (cron running, less active dev). This is the team, not infra. |
| **Trading capital + fees** | $0 (no live yet) | scales with capital×turnover | Exchange fees (~10 bps Binance) + funding + slippage — modeled in the Gate. Grows with deployed capital (i.e., with revenue). |

## The cheap-to-scale architecture (the one decision that matters)
**Tier the data:** Postgres holds the *hot* slice (recent + the coins you actually trade) for fast point-in-time
queries; the *full multi-year history* lives as **parquet on Cloudflare R2** and is read on-demand by backtests
(DuckDB/polars query parquet directly, no DB needed). Result: **Postgres stays ~$25/mo essentially forever**, and
data scales to terabytes for **single-digit $/mo**. This is the single biggest scaling lever — build it once the
hot DB approaches the 8 GB Pro cap (we're at ~6 GB now, so soon-ish).

## Realistic total infra at scale
- **Today:** ~$130–255/mo (mostly Claude). Infra ~$50.
- **At meaningful scale (many sources, TBs of history, frequent sweeps), tiered correctly:** infra still **< $100/mo**
  (Postgres $25 + R2 ~$15 + Modal pay-per-use ~$10–30 + Railway/Vercel ~$30 + CI ~$5). **Claude is still the biggest
  line** — and that's a *choice* you scale with build intensity.
- **The expensive thing was never infra — it's AI-dev time + trading capital, and both scale with actual progress/revenue.**

## Principle
Spend on the **search** stays lean and architected (tiering, free sources, pay-per-use). Spend on **capital** only
after a forward-test survivor. Never pre-buy a VPS or scale Postgres for cold data — those are the expensive mistakes.
