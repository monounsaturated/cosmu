# Leakage audit — ALL wired alt-features

Report-only behavioural audit of the three-disconfirmer leakage tripwire (`cosmu.research.leakage_tripwire.audit_feature`) over EVERY enabled, store-routed alt-data feature's REAL point-in-time series. The ~36 wired alt-features were hand-stamped PIT-honest by CONVENTION; this audits that convention against the data. PROPOSE-ONLY: it never moves money, runs no backtest, changes no Gate constant, and reads the store read-only.

**Verdict: NO LEAK FOUND** — 79 features · 2 PASS · 40 WARN · 0 FAIL · 37 SKIP.

- **FAIL** = a positive look-ahead (value joined before knowable, or lagging the feature beats the live read = a baked-in peek). A real leak; fails the run (non-zero exit).
- **WARN** = no look-ahead, but the IC sits inside the shuffled band (noise/artefact smell). Advisory only — a weak/dead feature is not a leak (the Gate disposes weak signals).
- **SKIP** = insufficient data to reason about (no store series, or too few joined PIT obs).
- **PASS** = strictly as-of join, no baked-in peek, IC survives the shuffle null.

| feature | source | verdict | scope | n_obs | real_ic | reason |
|---|---|---|---|---|---|---|
| `alt_rank` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.0602 | forward-shift tripped but UNCONFIRMED (live|IC|=0.0602 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.0602, null_mean|IC|=0.0736, p=0.4950) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `astro_jupiter_longitude` | astro | **WARN** | BTCUSDT | 82 | -0.1155 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1155 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1155, null_mean|IC|=0.0911, p=0.3465) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `astro_lunar_phase` | astro | **WARN** | BTCUSDT | 82 | +0.0002 | IC inside shuffled band (real|IC|=0.0002, null_mean|IC|=0.1064, p=1.0000) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `astro_saturn_longitude` | astro | **WARN** | BTCUSDT | 82 | -0.1155 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1155 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1155, null_mean|IC|=0.0911, p=0.3465) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `astro_sun_jupiter_aspect` | astro | **WARN** | BTCUSDT | 82 | +0.1155 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1155 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1155, null_mean|IC|=0.0911, p=0.3465) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `astro_sun_longitude` | astro | **WARN** | BTCUSDT | 82 | -0.1155 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1155 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1155, null_mean|IC|=0.0911, p=0.3465) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `btc_active_addresses` | blockchain.com | **WARN** | BTCUSDT | 82 | -0.0165 | IC inside shuffled band (real|IC|=0.0165, null_mean|IC|=0.0933, p=0.9010) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `btc_hashrate` | blockchain.com | **WARN** | BTCUSDT | 82 | -0.0149 | IC inside shuffled band (real|IC|=0.0149, null_mean|IC|=0.0921, p=0.8812) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `btc_mempool_size` | blockchain.com | **WARN** | BTCUSDT | 82 | -0.0650 | IC inside shuffled band (real|IC|=0.0650, null_mean|IC|=0.0875, p=0.5149) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `btc_tx_count` | blockchain.com | **WARN** | BTCUSDT | 82 | -0.0791 | forward-shift tripped but UNCONFIRMED (live|IC|=0.0791 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.0791, null_mean|IC|=0.0919, p=0.4653) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `contributors_active` | lunarcrush | **WARN** | BTCUSDT | 82 | +0.0567 | forward-shift tripped but UNCONFIRMED (live|IC|=0.0567 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.0567, null_mean|IC|=0.0876, p=0.6733) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `credit_spread` | fred | **WARN** | BTCUSDT | 82 | +0.1578 | IC inside shuffled band (real|IC|=0.1578, null_mean|IC|=0.0907, p=0.1485) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `defi_tvl` | defillama | **WARN** | BTCUSDT | 599 | -0.0510 | IC inside shuffled band (real|IC|=0.0510, null_mean|IC|=0.0334, p=0.2277) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `dvol` | deribit | **WARN** | BTCUSDT | 69 | +0.2027 | forward-shift tripped but UNCONFIRMED (live|IC|=0.2027 < 0.3 or n=69 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.2027, null_mean|IC|=0.0898, p=0.0594) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `dxy` | fred | **WARN** | BTCUSDT | 82 | -0.0261 | available_at wrong-winner x1 with 0 future-value violations (same-timestamp revision tie-break, not a look-ahead); IC inside shuffled band (real|IC|=0.0261, null_mean|IC|=0.0787, p=0.7822) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `eurusd` | stooq | **WARN** | BTCUSDT | 599 | -0.0257 | IC inside shuffled band (real|IC|=0.0257, null_mean|IC|=0.0336, p=0.5545) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `fear_greed` | alternative.me | **WARN** | BTCUSDT | 599 | +0.0266 | IC inside shuffled band (real|IC|=0.0266, null_mean|IC|=0.0327, p=0.5644) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `fed_funds_rate` | fred | **WARN** | BTCUSDT | 82 | +0.1938 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1938 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1938, null_mean|IC|=0.0822, p=0.0594) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `funding_rate` | ccxt | **WARN** | BTCUSDT | 599 | -0.0115 | IC inside shuffled band (real|IC|=0.0115, null_mean|IC|=0.0358, p=0.8317) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `galaxy_score` | lunarcrush | **WARN** | BTCUSDT | 82 | +0.0058 | IC inside shuffled band (real|IC|=0.0058, null_mean|IC|=0.0842, p=0.9802) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `gold_xau` | stooq | **WARN** | BTCUSDT | 599 | -0.0641 | IC inside shuffled band (real|IC|=0.0641, null_mean|IC|=0.0331, p=0.1287) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `macro_regime` | fred | **WARN** | BTCUSDT | 82 | +0.1773 | IC inside shuffled band (real|IC|=0.1773, null_mean|IC|=0.0868, p=0.1089) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `market_cap_usd` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.1184 | IC inside shuffled band (real|IC|=0.1184, null_mean|IC|=0.0808, p=0.2673) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `market_dominance` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.0449 | IC inside shuffled band (real|IC|=0.0449, null_mean|IC|=0.0844, p=0.6436) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `open_interest` | exchange | **WARN** | BTCUSDT | 30 | -0.1475 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1475 < 0.3 or n=30 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1475, null_mean|IC|=0.1440, p=0.3960) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `pm_book_depth` | polymarket_clob | **WARN** | BTCUSDT | 408 | -0.0937 | IC inside shuffled band (real|IC|=0.0937, null_mean|IC|=0.0456, p=0.1386) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `pm_implied_prob` | polymarket_clob | **WARN** | BTCUSDT | 408 | -0.0478 | IC inside shuffled band (real|IC|=0.0478, null_mean|IC|=0.0433, p=0.4554) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `pm_prob_velocity` | polymarket_clob | **WARN** | BTCUSDT | 407 | -0.0110 | IC inside shuffled band (real|IC|=0.0110, null_mean|IC|=0.0321, p=0.7525) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `posts_active` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.0992 | IC inside shuffled band (real|IC|=0.0992, null_mean|IC|=0.0800, p=0.3663) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `price_usd` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.1200 | IC inside shuffled band (real|IC|=0.1200, null_mean|IC|=0.0807, p=0.3069) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `silver_xag` | stooq | **WARN** | BTCUSDT | 599 | -0.0772 | IC inside shuffled band (real|IC|=0.0772, null_mean|IC|=0.0352, p=0.0990) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `social_dominance` | lunarcrush | **WARN** | BTCUSDT | 82 | +0.1063 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1063 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1063, null_mean|IC|=0.0933, p=0.3960) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `social_sentiment` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.1331 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1331 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1331, null_mean|IC|=0.0954, p=0.2772) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `social_volume` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.0045 | IC inside shuffled band (real|IC|=0.0045, null_mean|IC|=0.0780, p=0.9505) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `spam` | lunarcrush | **WARN** | BTCUSDT | 82 | -0.1591 | IC inside shuffled band (real|IC|=0.1591, null_mean|IC|=0.0683, p=0.0891) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `usdjpy` | stooq | **WARN** | BTCUSDT | 599 | -0.0476 | IC inside shuffled band (real|IC|=0.0476, null_mean|IC|=0.0378, p=0.2871) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `vix_level` | fred | **WARN** | BTCUSDT | 82 | +0.1118 | forward-shift tripped but UNCONFIRMED (live|IC|=0.1118 < 0.3 or n=82 < 60) — shift-noise on a thin/smooth series, NOT a confirmed leak; IC inside shuffled band (real|IC|=0.1118, null_mean|IC|=0.0831, p=0.2574) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `volume_24h_usd` | lunarcrush | **WARN** | BTCUSDT | 82 | +0.0124 | IC inside shuffled band (real|IC|=0.0124, null_mean|IC|=0.0966, p=0.9604) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `wti_crude` | stooq | **WARN** | BTCUSDT | 599 | +0.0169 | IC inside shuffled band (real|IC|=0.0169, null_mean|IC|=0.0346, p=0.6931) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `yield_curve_2s10s` | fred | **WARN** | BTCUSDT | 82 | +0.1773 | IC inside shuffled band (real|IC|=0.1773, null_mean|IC|=0.0868, p=0.1089) — noise/artefact smell, NOT a leak (the Gate disposes weak signals) |
| `cg_btc_dominance` | coingecko | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `cg_market_cap` | coingecko | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `cg_total_volume` | coingecko | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `cryptopanic_bearish_votes` | cryptopanic | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `cryptopanic_bullish_votes` | cryptopanic | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `fed_balance_sheet_usd` | fred | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `gdelt_news_volume` | gdelt_counts | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `gdelt_tone` | gdelt | **SKIP** | BTCUSDT | 19 | +0.0000 | only 19 joined PIT obs (< 30) — too thin to reason about |
| `initial_claims` | fred | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `insider_buy_ratio` | sec_edgar | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `jet_colocation` | opensky | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `net_liquidity_usd` | fred | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `news_event_score` | news | **SKIP** | BTCUSDT | 12 | +0.0000 | only 12 joined PIT obs (< 30) — too thin to reason about |
| `news_sentiment` | news_headlines | **SKIP** | BTCUSDT | 16 | +0.0000 | only 16 joined PIT obs (< 30) — too thin to reason about |
| `nfci` | fred | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `noaa_kp_index` | noaa | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `opensky_daily_flights` | opensky_daily | **SKIP** | BTCUSDT | 7 | +0.0000 | only 7 joined PIT obs (< 30) — too thin to reason about |
| `osint_air_activity` | opensky | **SKIP** | BTCUSDT | 9 | +0.0000 | only 9 joined PIT obs (< 30) — too thin to reason about |
| `perp_spot_basis` | exchange | **SKIP** | BTCUSDT | 9 | +0.0000 | only 9 joined PIT obs (< 30) — too thin to reason about |
| `pm_risk_on` | polymarket | **SKIP** | BTCUSDT | 7 | +0.0000 | only 7 joined PIT obs (< 30) — too thin to reason about |
| `putcall_ratio` | cboe | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `reddit_comment_volume` | reddit_volume | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `reddit_post_volume` | reddit_volume | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `reddit_sentiment` | reddit | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `reg_risk_crypto` | llm_index | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `risk_on_off` | llm_index | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `rss_news_count` | rss | **SKIP** | BTCUSDT | 6 | +0.0000 | only 6 joined PIT obs (< 30) — too thin to reason about |
| `stablecoin_eth_share` | defillama | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `stablecoin_mcap` | defillama | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `stablecoin_net_flow_usd` | defillama | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `twitter_sentiment` | xai | **SKIP** |  | 0 | +0.0000 | no store series / never joins any bar |
| `usgs_earthquake_count` | usgs | **SKIP** | BTCUSDT | 6 | +0.0000 | only 6 joined PIT obs (< 30) — too thin to reason about |
| `usgs_max_magnitude` | usgs | **SKIP** | BTCUSDT | 6 | +0.0000 | only 6 joined PIT obs (< 30) — too thin to reason about |
| `weather_hub_stress` | openmeteo | **SKIP** | BTCUSDT | 6 | +0.0000 | only 6 joined PIT obs (< 30) — too thin to reason about |
| `wiki_pageviews` | wikimedia | **SKIP** | BTCUSDT | 7 | +0.0000 | only 7 joined PIT obs (< 30) — too thin to reason about |
| `wiki_pageviews_log` | wikimedia | **SKIP** | BTCUSDT | 7 | +0.0000 | only 7 joined PIT obs (< 30) — too thin to reason about |
| `wiki_pageviews_zscore` | wikimedia | **SKIP** | BTCUSDT | 7 | +0.0000 | only 7 joined PIT obs (< 30) — too thin to reason about |
| `ndx_index` | stooq | **PASS** | BTCUSDT | 599 | -0.0912 | strictly as-of join, no baked-in peek, IC survives shuffle |
| `spx_index` | stooq | **PASS** | BTCUSDT | 599 | -0.0874 | strictly as-of join, no baked-in peek, IC survives shuffle |

## Limitations (read before trusting a clean verdict)

- **Thin real history dominates.** Most alt-features have only ~50-82 daily points joined to the bars (many newly-wired sources have weeks, not years), and 37 have too few / no store rows to score at all (SKIP). The audit can only CONFIRM or rule out a leak where the data is deep enough — a SKIP is *not* a clean bill of health, it is *unaudited for lack of data*.
- **The forward-shift check is noisy on short, smooth daily series with overlapping h=1 returns.** A near-zero, slowly-varying feature's |IC| jitters across a one-bar shift and can trip the tripwire's forward-shift sanity by chance — proven by the NON-CAUSAL astro controls tripping it identically (they cannot have a real look-ahead by construction). This audit therefore only CONFIRMS a forward-shift trip as a leak when the live |IC| is strong (>= 0.3) AND n >= 60; weaker/thinner trips are surfaced as WARN, never a false FAIL. The synthetic leaked control (live|IC| ~0.58-0.82) clears that bar, so a genuine baked-in peek is still caught.
- **A pure available_at wrong-winner with zero future-value violations is a same-timestamp revision tie-break, not a look-ahead** — downgraded to WARN (e.g. `dxy`).
- **Re-run as history deepens.** The right cadence is to re-run this audit periodically; a feature that is SKIP today should graduate to PASS/WARN/FAIL once it accrues >= 30-60 PIT observations.
