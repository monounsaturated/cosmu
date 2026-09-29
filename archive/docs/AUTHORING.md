# Strategy-authoring fiche (AUTHORING.md)

> **GENERATED — do not edit by hand.** Regenerate from the code with `cd apps/engine && python3 -m cosmu.docs.authoring_fiche`.
> Every table below is dumped live from `cosmu.config.feature_registry` and `cosmu.strategy.spec`, so this reference can never drift from the real vocabulary/schema. It is the standardized, never-drifting reference for authoring a `StrategySpec` — usable by both a human and Claude Code.

A spec must clear `validate_spec` (`cosmu/strategy/static_check.py`): **every threshold a `ParamRef` in `param_space`** · **≥1 entry `Condition`** (indicator specs) · **non-empty `rationale`** · feature names from the registry only. See `.claude/skills/create-strategy/SKILL.md` for the authoring workflow and the **Exit & Entry toolbox** wiring matrix (which exits actually run in paper/live today).

## Feature vocabulary

Every condition/meta-label/funding feature MUST reference one of these **96 enabled** registry names (an unknown name is rejected by `validate_spec` as `unknown_feature`). Disabled features (mislabeled / unwired / quarantined) are intentionally absent. Source of truth: `cosmu/config/feature_registry.py::feature_names()`.

### On-bar TA features (no ingest — pure price, `parquet_bars`)

These compute straight off the OHLCV bars — no alt-data join, no key, available everywhere.

| feature | source | tier | as-of |
|---------|--------|------|-------|
| `ret_Nd` | parquet_bars | tier0 | bar close time |
| `rsi` | parquet_bars | tier0 | bar close time |
| `adx` | parquet_bars | tier0 | bar close time |
| `atr` | parquet_bars | tier0 | bar close time |
| `bb_z` | parquet_bars | tier0 | bar close time |
| `bb_width` | parquet_bars | tier0 | bar close time |
| `range_position` | parquet_bars | tier0 | bar close time |
| `vol_realized` | parquet_bars | tier0 | bar close time |
| `xsec_momentum_rank` | parquet_bars | tier0 | bar close time (cross-sectional rank computed over instruments present at bar close — point-in-time, no survivorship lo… |

### Alt-data features (87 — require an ingest source / key)

Each needs its point-in-time source ingested (some are key-gated; non-causal **controls** are wired honestly for the Gate to KILL). Vet a new feed with `/profile-source` before authoring on it.

| feature | source | tier | as-of |
|---------|--------|------|-------|
| `alt_rank` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `astro_jupiter_longitude` | astro | tier1 | deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision) |
| `astro_lunar_phase` | astro | tier1 | deterministic per-day geometry, available_at = midnight UTC of the day (knowable at day-start; no look-ahead, no revisi… |
| `astro_saturn_longitude` | astro | tier1 | deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision) |
| `astro_sun_jupiter_aspect` | astro | tier1 | deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision) |
| `astro_sun_longitude` | astro | tier1 | deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision) |
| `author_authority` | social_authority | tier1 | snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass |
| `authority_weighted_claim_signal` | social_authority | tier1 | snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass |
| `btc_active_addresses` | blockchain.com | tier1 | daily on-chain count, available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Recent poin… |
| `btc_hashrate` | blockchain.com | tier1 | daily on-chain level, available_at = obs_day + 1 day midnight UTC (blockchain.com publishes a full UTC day with ≥~1-day… |
| `btc_mempool_size` | blockchain.com | tier1 | daily on-chain level (bytes), available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Rec… |
| `btc_social_accel` | lunarcrush | tier1 | BTC daily social bucket (next-day availability floor); BTC social_volume log-change broadcast to all symbols |
| `btc_tx_count` | blockchain.com | tier1 | daily on-chain count, available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Recent poin… |
| `cg_btc_dominance` | coingecko | tier1 | CURRENT snapshot from /global, available_at = fetch time (we only knew it when we pulled it — honest, never back-dated;… |
| `cg_market_cap` | coingecko | tier1 | daily per-coin market cap, available_at = obs_day + 1 day (daily aggregate finalized after day close; knowable T+1; no… |
| `cg_total_volume` | coingecko | tier1 | daily per-coin 24h total volume, available_at = obs_day + 1 day (daily aggregate finalized after day close; knowable T+… |
| `contributors_active` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `credit_spread` | fred | tier0 | daily publication time |
| `cryptopanic_bearish_votes` | cryptopanic | tier1 | 24h rolling window snapshot, available_at = fetch time (vote counts are mutable — captured at fetch, never rewritten) |
| `cryptopanic_bullish_votes` | cryptopanic | tier1 | 24h rolling window snapshot, available_at = fetch time (vote counts are mutable — captured at fetch, never rewritten) |
| `defi_tvl` | defillama | tier0 | daily publication time (next-day availability floor) |
| `dvol` | deribit | tier0 | daily close (next-day availability floor — DVOL bar opens at midnight UTC and is finalized at day-end; no look-ahead) |
| `dxy` | fred | tier0 | daily publication time |
| `eurusd` | stooq | tier0 | daily close (next-day availability floor) |
| `fear_greed` | alternative.me | tier0 | daily publication time (next-day availability) |
| `fed_balance_sheet_usd` | fred | tier1 | weekly H.4.1 reference (Wednesday), available_at = ts + 8 days (CONSERVATIVE publication-lag floor; the keyless fredgra… |
| `fed_funds_rate` | fred | tier0 | FRED release time (next-day availability floor) |
| `funding_rate` | ccxt | tier0 | exchange publication time |
| `galaxy_score` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `galaxy_score_z` | lunarcrush | tier1 | daily social bucket (next-day availability floor); trailing 30d within-asset z of galaxy_score |
| `gdelt_news_volume` | gdelt_counts | tier1 | daily per-topic article count, available_at = obs_day + 1 day midnight UTC (a full UTC day's count is complete only aft… |
| `gdelt_tone` | gdelt | tier1 | daily geopolitical news tone (next-day availability floor — a day's indexed articles are closed by end-of-day; no look-… |
| `gold_xau` | stooq | tier0 | daily close (next-day availability floor) |
| `initial_claims` | fred | tier0 | FRED/ALFRED initial-release time (realtime_start = the actual Thursday release; ~8-day ref lag; no look-ahead) |
| `insider_buy_ratio` | sec_edgar | tier1 | Form 4 acceptanceDateTime; only filings accepted <= as_of are used (no look-ahead); the trailing-window aggregate's ava… |
| `jet_colocation` | opensky | tier1 | daily co-location count; available_at = obs_day + 1 day 00:00 UTC (>=1-day OpenSky publication lag; no look-ahead); a g… |
| `liquidation_cascade` | coinglass | tier0 | liquidation bucket close time (next-bucket availability floor) |
| `macro_regime` | fred | tier0 | FRED release time (next-day availability floor) |
| `market_cap_usd` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `market_dominance` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `ndx_index` | stooq | tier0 | daily close (next-day availability floor) |
| `net_liquidity_usd` | fred | tier1 | weekly H.4.1 reference (Wednesday), available_at = ts + 8 days (CONSERVATIVE publication-lag floor; keyless CSV has no… |
| `news_event_score` | news | tier1 | headline availability time (ts == available_at; point-in-time, no look-ahead) |
| `news_sentiment` | news_headlines | tier1 | LLM-standardized at headline availability time |
| `nfci` | fred | tier0 | FRED/ALFRED initial-release time (realtime_start = the actual Wednesday release; no look-ahead) |
| `noaa_kp_index` | noaa | tier1 | daily-max Kp; live-query available_at = as_of (snapshot); daily-batch floor = obs_day + 1; gap = None, never 0 |
| `open_interest` | exchange | tier0 | exchange publication time |
| `opensky_daily_flights` | opensky_daily | tier1 | daily unique-aircraft count, available_at = flight_date + 1 day midnight UTC (≥1-day publication lag; no look-ahead) |
| `osint_air_activity` | opensky | tier1 | live ADS-B snapshot time (availability == observation, no look-ahead) |
| `perp_spot_basis` | exchange | tier0 | exchange publication time |
| `pm_book_depth` | polymarket_clob | tier0 | CLOB snapshot time |
| `pm_implied_prob` | polymarket_clob | tier0 | CLOB snapshot time |
| `pm_prob_velocity` | polymarket_clob | tier0 | CLOB snapshot time |
| `pm_risk_on` | polymarket | tier0 | CLOB midpoint at quote time (no lag) |
| `posts_active` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `price_usd` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `putcall_ratio` | cboe | tier0 | daily publication time (next-day availability floor) |
| `reddit_comment_volume` | reddit_volume | tier1 | daily count, available_at = day AFTER the observation date (full closed day; no look-ahead) |
| `reddit_post_volume` | reddit_volume | tier1 | daily count, available_at = day AFTER the observation date (full closed day; no look-ahead) |
| `reddit_sentiment` | reddit | tier1 | public hot.json read time (availability == observation, no look-ahead) |
| `reg_risk_crypto` | llm_index | tier1 | LLM index minted at evidence-availability time (availability == observation, no look-ahead) |
| `risk_on_off` | llm_index | tier1 | LLM index minted at evidence-availability time (availability == observation, no look-ahead) |
| `rss_news_count` | rss | tier1 | trailing 24h headline count from public RSS feeds; available_at == fetch time (each item's pubDate is its own PIT marke… |
| `silver_xag` | stooq | tier0 | daily close (next-day availability floor) |
| `social_attention_z` | lunarcrush | tier1 | daily social bucket (next-day availability floor); trailing 30d within-asset z of social_volume |
| `social_dominance` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `social_excess_attention_z` | lunarcrush | tier1 | daily social bucket (next-day availability floor); trailing 30d within-asset z of ln(social_volume)-ln(dollar_volume) |
| `social_sentiment` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `social_volume` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `social_volume_accel` | lunarcrush | tier1 | daily social bucket (next-day availability floor); ln(v_t/v_{t-1}), available_at of the later point |
| `spam` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `spx_index` | stooq | tier0 | daily close (next-day availability floor) |
| `stablecoin_eth_share` | defillama | tier1 | fraction of total float on Ethereum [0,1], available_at = obs_day + 1 day (daily aggregate finalized after day close; k… |
| `stablecoin_mcap` | defillama | tier1 | daily total, available_at = obs_day + 1 day (a daily aggregate is finalized after the day closes; knowable T+1; no look… |
| `stablecoin_net_flow_usd` | defillama | tier1 | signed day-over-day mcap delta, available_at = obs_day + 1 day (a daily aggregate is finalized after the UTC day closes… |
| `twitter_sentiment` | xai | tier1 | xAI LiveSearch fetch time (availability == observation, no look-ahead) |
| `usdjpy` | stooq | tier0 | daily close (next-day availability floor) |
| `usgs_earthquake_count` | usgs | tier1 | past-24h global count; live-query available_at = as_of (snapshot); daily-batch floor = obs_day + 1 (no look-ahead) |
| `usgs_max_magnitude` | usgs | tier1 | past-24h global max magnitude; live-query available_at = as_of (snapshot); gap = None, never 0 |
| `vix_level` | fred | tier0 | FRED release time (next-day availability floor) |
| `volume_24h_usd` | lunarcrush | tier1 | daily social bucket (next-day availability floor) |
| `weather_hub_stress` | openmeteo | tier1 | daily cross-hub stress score, available_at = obs_date + 1 day 06:00 UTC (Open-Meteo reanalysis finishes next day; no lo… |
| `wiki_pageviews` | wikimedia | tier1 | daily count, available_at = obs_date + 1 day midnight UTC (Wikimedia publishes day-T on day T+1; immutable, no revision) |
| `wiki_pageviews_log` | wikimedia | tier1 | daily count, available_at = obs_date + 1 day midnight UTC (immutable, no revision) |
| `wiki_pageviews_zscore` | wikimedia | tier1 | daily count, available_at = obs_date + 1 day midnight UTC; trailing 30d within-article z of log views (strictly causal) |
| `wti_crude` | stooq | tier0 | daily close (next-day availability floor) |
| `yield_curve_2s10s` | fred | tier0 | daily publication time |

## Spec field lists (`cosmu/strategy/spec.py`)

Field names + types, dumped live from each pydantic model's `model_fields`. Thresholds are `ParamRef` (a `{"param": ...}` pointer into `param_space`) — never a literal number.

### ExitRules

The exit contract: single stop/take (required) + optional signal exits, time-stop, and a composable `plan`.

| field | type | default |
|-------|------|---------|
| `stop_loss` | `ParamRef` | `— (required)` |
| `take_profit` | `ParamRef` | `— (required)` |
| `signal_exits` | `list[Condition]` | `list()` |
| `time_stop_days` | `Optional[ParamRef]` | `None` |
| `plan` | `Optional[ExitPlan]` | `None` |

### ExitPlan

Composable exit structure layered on the single stop/take — multi-TP scale-out, break-even, runner trail.

| field | type | default |
|-------|------|---------|
| `multi_tp` | `list[TakeProfitLeg]` | `list()` |
| `break_even_after_tp1` | `bool` | `False` |
| `runner_trail` | `Optional[ParamRef]` | `None` |

### EntrySetup

Composable entry structure alongside `entry` conditions — MA-trend filter, ORB, FVG retest (long/upside-only).

| field | type | default |
|-------|------|---------|
| `ma_trend_filter` | `Optional[MaTrendFilter]` | `None` |
| `orb` | `Optional[OpeningRangeBreakout]` | `None` |
| `fvg` | `Optional[FairValueGap]` | `None` |

### RiskRules

Position-risk knobs read by the deterministic sizer (`master/sizing.py`).

| field | type | default |
|-------|------|---------|
| `max_concurrent_positions` | `int` | `3` |
| `max_position_pct` | `float` | `0.05` |
| `conviction` | `float` | `0.5` |

### MetaLabel

Triple-barrier meta-labeling — a secondary logistic that SIZES/SKIPS the primary trade (never flips side).

| field | type | default |
|-------|------|---------|
| `features` | `list[FeatureRef]` | `— (required)` |
| `prob_threshold` | `ParamRef` | `— (required)` |
| `sizing` | `Literal['skip', 'proportional']` | `'skip'` |

## `param_space` kinds (`ParamSpace`)

Every threshold/lookback is a named entry in `param_space`. The Finder grid fits the value — the spec carries the SEARCH SPACE, never a magic number.

| kind | fields | meaning |
|------|--------|---------|
| `int` | `lo`, `hi`, `step` | integer grid from `lo` to `hi` in `step` increments (e.g. a lookback window) |
| `float` | `lo`, `hi` | continuous range from `lo` to `hi` (e.g. a stop %, a funding floor) |
| `choice` | `choices` | an explicit list of candidate values |
