# LunarCrush Data Dictionary — what we hoarded & what it means (lesson)

Reusable reference for humans AND LLM agents (strategy-authors, feature-wiring). What every LunarCrush field
in our Postgres `alt_data` table means, a sample value, and how it's used as a trading signal.

## 📦 Shape of what we have
- **Provider:** `lunarcrush` · **Grain:** one row **per coin, per day** · **Span:** ~2020-01-01 → 2026-06-06 (~6.4 yr)
- **Universe:** ~980 coins (all venues we might trade: Binance/Kraken/Hyperliquid/Coinbase) · **~10.5M rows · 12 metrics/coin**
- **Point-in-time:** each daily point is stamped `available_at = ts + 1 day` → a backtest can't see a value before
  it was knowable (no naive look-ahead).
- ⚠️ **Single backfill caveat:** it was pulled in ONE shot, so if LunarCrush *revises history*, our snapshot may be
  subtly future-informed. → social signals are a **SCREEN only**; a survivor must clear a forward-test before live.

## 🔑 The 12 metrics (stored_name ← API field · sample BTC value · meaning · trading use)

| Metric | ← API | Sample (BTC/day) | 💬 What it means | 🎯 Trading use |
|---|---|---|---|---|
| `social_volume` | interactions | 188,715,170 | 🗣️ Raw count of all social interactions (posts+likes+comments+shares) about the coin | Attention spikes; volume-acceleration lead |
| `social_sentiment` | sentiment | 66 (/100) | 🙂 0–100 score of how positive the chatter is (>50 = net bullish) | Sentiment-vs-price divergence |
| `galaxy_score` | galaxy_score | 50 (/100) | 🌌 LunarCrush's proprietary 0–100 "health" blend of price momentum + social + market | Blended momentum gauge (⚠️ blends price → semi-tautological) |
| `alt_rank` | alt_rank | 85 (1=best) | 🏅 Rank of the coin by price-vs-social performance (LOWER is better) | Rank-improvement momentum (a coin climbing) |
| `social_dominance` | social_dominance | 49.43 (%) | 📊 The coin's **% share of ALL crypto social volume** (already normalized) | ⭐ The cleanest cross-sectional "share-of-voice" signal |
| `market_dominance` | market_dominance | 58.43 (%) | 🏦 The coin's % share of total crypto market cap | Regime/risk-on-off (BTC dominance ↑ = rotation to safety) |
| `contributors_active` | contributors_active | 98,358 | 👥 Unique authors posting about it (BREADTH of attention) | Organic vs manufactured: many authors = real interest |
| `posts_active` | posts_active | 241,746 | 📝 Count of active posts about it | Posts ÷ contributors = posts-per-author (bot/spam tell) |
| `spam` | spam | 9,174 | 🚫 Posts flagged as spam/low-quality | NOISE filter — de-weight spikes that are mostly spam |
| `market_cap_usd` | market_cap | 1,215,920,246,110 ($1.2T) | 💰 Market cap in USD | Universe/size filter, normalization base |
| `volume_24h_usd` | volume_24h | 64,788,804,406 ($64.8B) | 💵 24h trading volume in USD | Liquidity filter — can we trade it without slippage? |
| `price_usd` | close | 60,640.50 ($) | 📈 Daily close price | Returns; cross-check vs Binance bars |

## 🧠 The lesson (how to actually USE this — for the strategy-author LLM)
1. **Don't trade raw levels — they drift massively** (absolute social volume grew ~160× over the years). The SIGNAL
   lives in **normalized / derived** forms: z-scores, %-changes (acceleration), and ratios.
2. **`social_dominance` is the gold one** — it's *already* normalized (share of total), so it's comparable across coins
   and across time. Cross-sectional "which coin is gaining share of voice" is the least-arbitraged angle.
3. **Quality > quantity:** `contributors_active` (breadth) and `spam` (noise) separate organic attention from a bot
   pump. A volume spike with few contributors + high spam = ignore. Many contributors + low spam = real.
4. **`galaxy_score` and `alt_rank` already blend price in** → using them as "alpha" risks just re-discovering price
   momentum (tautology). Treat them as conditioners, test the disconfirmer.
5. **The honest path:** these are FEATURES the deterministic Gate judges — the LLM only standardizes/derives them
   (point-in-time, frozen transform), it never decides trades. Social edge = screen → forward-test → live.

## Where it's wired
Routed in `data/providers/store.py` `_STORE_PROVIDER_OF` (all → `lunarcrush`, per-symbol, tier1/low-confidence),
fetched by `lunarcrush.py` `_FIELD`, read point-in-time by `StoreBackedAltProvider`, consumed by
`research/social_signal_cohort.py`. The 3 to test first: see `docs/reports/edge-plan-2026-06-06.md`.
