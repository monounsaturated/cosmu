# intent: define the named feature vocabulary the lab agent may reference; inputs: config/static seed; outputs: FeatureDefinition list; invariants: every feature has as-of semantics and a prior hypothesis.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Pinned transform version for the xAI/Grok Twitter sentiment source.  Bump this string whenever
# the scoring prompt or weighting logic changes so a gate-passed survivor remains re-runnable.
TWITTER_TRANSFORM_VERSION = "xai-twitter-sentiment-v1"

# Pinned transform version for the social-authority features ("PageRank for credibility"). Bump when the
# claim-extraction prompt, the deterministic resolver/scoring, or the authority fusion changes, so a gate-passed
# survivor that depends on author authority stays re-runnable. Kept here (not imported from cosmu.mind) to avoid
# an import cycle; cosmu.mind.authority.AUTHORITY_VERSION carries the same string.
AUTHORITY_TRANSFORM_VERSION = "social-authority-v1"


class FeatureDefinition(BaseModel):
    name: str
    source: str
    tier: Literal["tier0", "tier1"]
    asset_classes: list[str]
    asof_semantics: str
    prior: str
    enabled: bool = True
    # Pins the (frozen, versioned) ingest transform a feature depends on, so a survivor is
    # re-runnable byte-for-byte. None = pure price/registry feature, no ingest transform.
    transform_version: str | None = None


FEATURE_REGISTRY: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(name="funding_rate", source="ccxt", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Funding extremes proxy crowded leverage; used as a long filter (spot, long-only).", transform_version="funding-zscore-v1"),
    FeatureDefinition(name="fear_greed", source="alternative.me", tier="tier0", asset_classes=["crypto"], asof_semantics="daily publication time (next-day availability)", prior="Crowd fear mean-reverts at swing horizon — buy fear, fade greed.", transform_version="feargreed-regime-v1"),
    FeatureDefinition(name="news_sentiment", source="news_headlines", tier="tier1", asset_classes=["crypto"], asof_semantics="LLM-standardized at headline availability time", prior="A positive news-flow shift precedes multi-day continuation before it is fully priced.", transform_version="news-sentiment-v1"),
    # --- cross-asset transfer features (Phase 1.6): one market's price IS another's feature. ---
    FeatureDefinition(name="pm_risk_on", source="polymarket", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="CLOB midpoint at quote time (no lag)", prior="Prediction-market odds on macro/risk events price the risk regime before it shows in any single asset's own price — a cross-asset risk-on/off tag.", transform_version="pm-riskon-v1"),
    # DISABLED (honesty fix): registered with a pinned transform but NEVER wired — there is no provider, no
    # ingest, and no computation that produces it (absent from _STORE_PROVIDER_OF and the catalog). An enabled
    # feature with no route AND no bar/cohort computation is dead weight the registry↔route guard now forbids;
    # disabled until a real cross-venue funding-transfer source exists. Still in FEATURE_REGISTRY (its metadata
    # is pinned) but dropped from feature_names()/the gate universe.
    FeatureDefinition(name="xasset_risk_appetite", source="ccxt", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="exchange publication time", prior="Crypto perp funding is a fast, 24/7 read on speculative risk appetite that leads slower equity/macro signals — transfer crypto's read onto equities.", transform_version="xasset-funding-v1", enabled=False),
    FeatureDefinition(name="macro_regime", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Macro regime (curve slope, real rates, liquidity) conditions risk premia across every asset class — a shared regime tag, not a single-market signal.", transform_version="macro-regime-v1"),
    FeatureDefinition(name="vix_level", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="VIX measures implied volatility; extremes signal regime shifts and mean-revert at swing horizon", transform_version="vix-level-v1"),
    FeatureDefinition(name="fed_funds_rate", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Federal funds rate changes drive risk premia across all asset classes", transform_version="fed-funds-v1"),
    FeatureDefinition(name="defi_tvl", source="defillama", tier="tier0", asset_classes=["crypto"], asof_semantics="daily publication time (next-day availability floor)", prior="DeFi TVL flows indicate risk appetite and liquidity across crypto protocols", transform_version="defi-tvl-v1"),
    FeatureDefinition(name="open_interest", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="OI changes reveal leverage build-up."),
    FeatureDefinition(name="perp_spot_basis", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Basis captures risk appetite and carry."),
    # DISABLED (honesty fix — TOP PRIORITY): this was NEVER on-chain exchange netflow. Its provider
    # (data/providers/onchain.ExchangeNetflowProvider) fetches Binance USDⓈ-M globalLongShortAccountRatio —
    # perp CROWD POSITIONING — and stored ratio-1.0 under a FABRICATED "net inflows precede sell pressure"
    # prior, at TIER-0 (high gate weight), on only ~30 days of data. That manufactured false positives at high
    # weight. Disabled: dropped from feature_names()/the gate universe and the ML panel. The provider, ingest
    # closure (catalog "netflow"), and store route remain so already-banked data is preserved (dormant, no
    # longer gate-weighted), pending an honest relabel to a tier1 perp_long_short_ratio with a real prior.
    FeatureDefinition(name="exchange_netflow", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="provider knowledge time", prior="MISLABELED Binance long/short ratio (perp crowd positioning), NOT on-chain netflow; fabricated prior — disabled pending honest relabel.", enabled=False),
    # DISABLED (honesty fix): MISLABELED. It ingests FRED "VIXCLS" — the VIX SPOT level, byte-identical to
    # vix_level — NOT a term slope (a real one needs VIX3M/VXVCLS minus VIXCLS, which is not ingested). Left
    # enabled it was a phantom DUPLICATE of vix_level under a false "term slope" prior, inflating the gate's
    # multiple-testing N for zero added signal. Dropped from feature_names()/the gate universe; the catalog
    # ingest + store route stay so banked rows are preserved (dormant), pending a real VXVCLS term-structure source.
    FeatureDefinition(name="vix_term_slope", source="fred/cboe", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="MISLABELED: ingests VIXCLS (the VIX SPOT level) identical to vix_level — NOT a term slope; disabled pending an honest VXVCLS/VIX3M source.", enabled=False),
    FeatureDefinition(name="putcall_ratio", source="cboe", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time (next-day availability floor)", prior="Sentiment extremes mean-revert at swing horizon.", transform_version="putcall-zscore-v1"),
    FeatureDefinition(name="liquidation_cascade", source="coinglass", tier="tier0", asset_classes=["crypto"], asof_semantics="liquidation bucket close time (next-bucket availability floor)", prior="A spike in total long+short liquidations marks forced deleveraging that overshoots — a cascade exhausts sellers and mean-reverts at the swing horizon.", transform_version="liquidation-cascade-zscore-v1"),
    # Best-effort OSINT ("watching planes"): aircraft activity from the free OpenSky Network as a crude,
    # LOW-CONFIDENCE macro-risk-appetite proxy. Availability == observation time (a live snapshot is only
    # knowable when taken — no look-ahead). tier1 + the explicit low-confidence prior mean it must earn its
    # place via out-of-sample; the gate down-weights it until it pays.
    FeatureDefinition(name="osint_air_activity", source="opensky", tier="tier1", asset_classes=["crypto", "equity"], asof_semantics="live ADS-B snapshot time (availability == observation, no look-ahead)", prior="Aircraft activity is a crude, low-confidence macro risk-appetite/economic-activity proxy (best-effort OSINT); must earn its place via OOS — flag low-confidence.", transform_version="osint-adsb-v1"),
    # DISABLED (honesty fix): the four equity/CFTC features below are registered but UNWIRED — no provider, no
    # ingest, no route, no computation produces them. The registry↔route guard forbids enabled-but-dead features;
    # disabled until a real data source is wired. Kept in FEATURE_REGISTRY (metadata intact), out of feature_names().
    FeatureDefinition(name="cftc_net_positioning", source="cftc", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="CFTC release time", prior="Crowded positioning can unwind.", enabled=False),
    FeatureDefinition(name="dxy", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Dollar strength changes risk appetite."),
    FeatureDefinition(name="yield_curve_2s10s", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Curve slope tracks macro regime."),
    FeatureDefinition(name="credit_spread", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Credit stress drives equity risk premia."),
    FeatureDefinition(name="days_to_earnings", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="Earnings windows alter drift and volatility.", enabled=False),
    FeatureDefinition(name="insider_buy_ratio", source="sec_edgar", tier="tier0", asset_classes=["equity"], asof_semantics="Form 4 publication time", prior="Insider buying can signal undervaluation.", enabled=False),
    FeatureDefinition(name="short_interest_ratio", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="High short interest can fuel squeezes.", enabled=False),
    FeatureDefinition(name="ret_Nd", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity", "prediction"], asof_semantics="bar close time", prior="Medium-term return captures momentum/reversal."),
    # Cross-sectional rank of N-day return across the universe at bar-close time: 0 = worst, 1 = best.
    # Computed from parquet_bars (same source as ret_Nd) at the bar close so it is point-in-time: rank is
    # derived only from instruments present at that bar (no survivorship look-ahead).  A high rank (near 1)
    # identifies the cross-sectional momentum leaders; a low rank (near 0) identifies the laggards.  The
    # lookback window mirrors ret_Nd (a fitted ParamRef in each strategy) so the rank is consistent with the
    # raw return it is derived from.  transform_version pins the ranking method (percentile, not ordinal) so a
    # gate-passed survivor is re-runnable byte-for-byte.
    FeatureDefinition(
        name="xsec_momentum_rank",
        source="parquet_bars",
        tier="tier0",
        asset_classes=["crypto", "equity"],
        asof_semantics="bar close time (cross-sectional rank computed over instruments present at bar close — point-in-time, no survivorship look-ahead)",
        prior=(
            "Cross-sectional percentile rank [0, 1] of N-day return across the screened universe at each bar close. "
            "High rank (→ 1) = relative momentum leader; low rank (→ 0) = relative momentum laggard. "
            "Ranking longs by top-rank and shorts by bottom-rank constructs a market-neutral book whose beta to the "
            "market cancels — the residual is pure cross-sectional momentum premium (documented in AQR / Jegadeesh–Titman). "
            "Must earn its place via OOS."
        ),
        transform_version="xsec-momentum-rank-v1",
    ),
    FeatureDefinition(name="atr", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ATR normalizes risk and stop distance."),
    FeatureDefinition(name="rsi", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="RSI captures overextension."),
    FeatureDefinition(name="adx", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ADX separates trend from chop."),
    FeatureDefinition(name="bb_z", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Band z-score captures statistically unusual price."),
    FeatureDefinition(name="bb_width", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Bollinger Bandwidth (±2σ band width / basis) measures range compression — a squeeze (low width) marks the coiled, low-vol range a reversion edge needs; an expansion flags the range breaking into a trend."),
    FeatureDefinition(name="vol_realized", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Realized vol gates capacity and risk."),
    # --- social feeds (tier1, low-confidence until validated OOS): Reddit crowd sentiment (free, no key) and
    # LunarCrush social metrics (key-gated; empty without a key). The gate down-weights tier1 until it pays. ---
    FeatureDefinition(name="reddit_sentiment", source="reddit", tier="tier1", asset_classes=["crypto"], asof_semantics="public hot.json read time (availability == observation, no look-ahead)", prior="Reddit crowd chatter (bull vs bear post mix) is a fast, low-confidence sentiment proxy — extremes may mean-revert at the swing horizon; must earn its place via OOS.", transform_version="reddit-sentiment-v1"),
    FeatureDefinition(name="social_volume", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="A surge in social volume can mark crowd attention that precedes (or exhausts) a move — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="social_sentiment", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush social sentiment is a crowd-mood proxy; a positive shift may precede continuation before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="galaxy_score", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush Galaxy Score blends price + social health into one rank; extremes are a low-confidence regime tag — must earn its place via OOS.", transform_version="lunarcrush-v1"),
    # The four remaining LunarCrush coin time-series fields, hoarded per coin alongside the three above
    # (scripts/lunarcrush_max_extract.py pulls all seven in one call). Same daily next-day-availability PIT
    # semantics; tier1 + low-confidence until validated OOS. alt_rank is LunarCrush's combined social+market
    # rank (1 = best, so a FALLING alt_rank = improving). market_cap_usd / volume_24h_usd / price_usd are the
    # vendor's own market series (distinct from the Binance bars — usable as cross-checks or scale normalizers).
    FeatureDefinition(name="alt_rank", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush AltRank blends social activity and market performance into one cross-sectional rank (1 = best); an IMPROVING rank (falling number) may flag an asset gaining relative social+price strength before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="market_cap_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's daily market-cap series; a size/scale normalizer and capacity guard rather than a directional signal — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="volume_24h_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's daily 24h traded-volume series; the dollar-volume denominator for excess-attention measures and a liquidity gate — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="price_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's own daily price series; a vendor cross-check of the Binance bars and a base for vendor-side return computations — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    # The final five LunarCrush coin fields hoarded per coin (scripts/lunarcrush_max_extract.py _COIN_FIELDS),
    # banked-but-unwired until now. Per-symbol, same daily next-day-availability PIT semantics; tier1 +
    # low-confidence until validated OOS. social_dominance / market_dominance are the coin's % share of all
    # crypto social volume / total market cap (normalized cross-sectional signals); contributors_active /
    # posts_active measure the breadth and raw count of the social signal; spam is a noise level that lets a
    # strategy de-weight low-quality social spikes.
    FeatureDefinition(name="social_dominance", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="A coin's share of ALL crypto social volume; a scale-stable cross-sectional attention signal — a rising social-dominance share may flag rotating crowd attention before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="market_dominance", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="A coin's share of total crypto market cap; a relative-size regime tag (dominance rotation between majors and alts) rather than a directional trigger — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="contributors_active", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="The count of unique authors talking about a coin; a breadth/quality read on the social signal — broad participation may distinguish durable attention from a single-account spike — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="posts_active", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="The active post count for a coin; a raw social-throughput measure that pairs with contributors_active to gauge attention intensity — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="spam", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's spam/noise level for a coin's social feed; a quality filter that lets a strategy de-weight low-quality social spikes rather than a directional signal — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    # --- NORMALIZED LunarCrush derivations (cosmu/research/social_norm.py): scale-stable, within-asset, PIT.
    # The raw levels above drift ~160x over 2020-26, so a fitted level threshold is always-true (the phase0
    # social-signal §4 trap). These decompose attention into CHANGE (leads +) vs ALTITUDE (leads -), which the
    # lead-lag probe shows carry OPPOSITE-signed information. tier1, low-confidence until validated OOS. ---
    FeatureDefinition(name="social_volume_accel", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); ln(v_t/v_{t-1}), available_at of the later point", prior="A FRESH jump in social attention (day-over-day log-change of social_volume) leads price up at k=1-3d (attention momentum) — distinct from, and opposite to, the elevated LEVEL.", transform_version="social-norm-v1"),
    FeatureDefinition(name="social_attention_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of social_volume", prior="SUSTAINED elevated social_volume (within-asset z of the level) leads price DOWN, worse with horizon — the crowd is already piled in. Used as a 'too crowded' altitude guard, not a long trigger.", transform_version="social-norm-v1"),
    FeatureDefinition(name="social_excess_attention_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of ln(social_volume)-ln(dollar_volume)", prior="Crowd loudness RELATIVE to money traded (social/dollar-volume) leads price UP at the ~1-week horizon (k=7 decile spread +1.8%, t=+5.77) — robust longer-horizon continuation the absolute-volume specs missed.", transform_version="social-norm-v1"),
    FeatureDefinition(name="galaxy_score_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of galaxy_score", prior="Within-asset z of galaxy_score crowd-health; a low-confidence regime tag (the top-decile drawdown asymmetry seen on a short sample did NOT robustly replicate on the full sample — registered for completeness, no spec rests on it).", transform_version="social-norm-v1"),
    FeatureDefinition(name="btc_social_accel", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="BTC daily social bucket (next-day availability floor); BTC social_volume log-change broadcast to all symbols", prior="A BTC social-attention spike leads the mean-ALT return at k=1d (cross-asset attention contagion) — BTC's crowd, read on the alts.", transform_version="social-norm-v1"),
    # xAI/Grok Twitter sentiment (key-gated: XAI_API_KEY required; returns [] without it).
    # The LLM ONLY standardizes/scores tweet text — it is NEVER on the gate/scoring/money path.
    # Both features are market-wide (the query covers crypto broadly, not a single asset).
    # tier1 + low-confidence until validated OOS; the gate down-weights until it earns its place.
    FeatureDefinition(
        name="twitter_sentiment",
        source="xai",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="xAI LiveSearch fetch time (availability == observation, no look-ahead)",
        prior=(
            "Real-time Twitter/X crypto sentiment scored by Grok on [-1, +1]; "
            "crowd social signal that may lead price at swing horizon — low-confidence until validated OOS."
        ),
        transform_version=TWITTER_TRANSFORM_VERSION,
    ),
    FeatureDefinition(
        name="twitter_influencer_sentiment",
        source="xai",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="xAI LiveSearch fetch time (availability == observation, no look-ahead)",
        prior=(
            "Influencer-weighted Twitter/X sentiment: each tweet's Grok score is weighted by the author's "
            "historical hit-rate (fraction of past calls followed by correct price direction). "
            "Accounts with higher empirical accuracy carry more weight. tier1 + low-confidence until validated OOS."
        ),
        transform_version=TWITTER_TRANSFORM_VERSION,
        # DISABLED: the InfluencerHitRateStore (xai_twitter.py:113) is still a stub returning 0.5 for every
        # account → twitter_influencer_sentiment is byte-identical to twitter_sentiment at all times, inflating
        # the gate's effective N (two entries, one signal). Re-enable once the real hit-rate store is wired
        # (BACKLOG.md:65: route through mind/authority.py social_authority or populate influencer_hit_rates table).
        enabled=False,
    ),
    # Event/news scorer: a typed, dated, point-in-time signal with sign [-1,+1] and magnitude [0,1].
    # The LLM (when keyed) standardizes/scores the headline text — ONLY at ingest, NEVER on the gate path.
    # Without an LLM key the offline lexicon is used (StandardizedNews path). tier1 + low-confidence
    # until validated OOS; the gate down-weights until it earns its place.
    FeatureDefinition(
        name="news_event_score",
        source="news",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="headline availability time (ts == available_at; point-in-time, no look-ahead)",
        prior=(
            "A typed, dated event/news signal: sign + magnitude derived from the headline text at ingest. "
            "Positive = bullish catalyst (approval, surge, adoption); negative = bearish event (hack, ban, crash). "
            "The LLM standardizes text only at ingest; NEVER on the gate/scoring/money path. "
            "tier1 + low-confidence until validated OOS."
        ),
        transform_version="news-event-score-v1",
    ),
    # --- LLM qualitative→quantitative INDEX scores (VISION §6): an LLM-as-judge standardizes narrative into a
    # rubric-anchored numeric score, stored POINT-IN-TIME WITH HISTORY so the gate can train on it. The LLM ONLY
    # proposes the number against an explicit rubric; the deterministic Gate alone disposes — NEVER the money path.
    # Both are market-wide + tier1 (low-confidence until validated OOS; the gate down-weights until it earns its
    # place). transform_version pins the rubric+prompt so a gate-passed survivor is re-runnable byte-for-byte. ---
    FeatureDefinition(
        name="reg_risk_crypto",
        source="llm_index",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="LLM index minted at evidence-availability time (availability == observation, no look-ahead)",
        prior=(
            "An LLM-as-judge standardizes qualitative regulatory news into a [0, 1] crackdown-pressure score "
            "against an explicit rubric (0 = supportive/clear, 1 = severe crackdown). A spike marks rising "
            "regulatory risk that may precede de-risking. The LLM proposes; the deterministic Gate disposes — "
            "low-confidence until validated OOS."
        ),
        transform_version="llm-index-v1",
    ),
    FeatureDefinition(
        name="risk_on_off",
        source="llm_index",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="LLM index minted at evidence-availability time (availability == observation, no look-ahead)",
        prior=(
            "An LLM-as-judge standardizes macro/geopolitical narrative into a [-1, +1] risk-appetite score "
            "against an explicit rubric (+1 risk-on, -1 risk-off) — a shared cross-asset regime tag. The LLM "
            "proposes; the deterministic Gate disposes — low-confidence until validated OOS."
        ),
        transform_version="llm-index-v1",
    ),
    # --- cross-asset daily price levels (free, no key) via Stooq/Yahoo: one asset class's price IS another's
    # macro feature. Each is market-wide, point-in-time (a daily close is known the next day — see
    # multiasset-daily-v1), and tier0 like the other liquid macro reads (dxy/vix). They condition the shared
    # risk regime across crypto + equity, so each spans both classes. ---
    FeatureDefinition(name="gold_xau", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Gold is the canonical risk-off / real-rate hedge; its level and trend tag the macro risk regime that conditions crypto + equity premia.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="silver_xag", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Silver blends a precious-metal hedge with industrial demand; the gold/silver behaviour is a cyclical risk-appetite read.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="wti_crude", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Crude oil is a growth + inflation impulse; sharp moves precede shifts in risk premia across every class.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="spx_index", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="The S&P 500 is the global risk-on benchmark; crypto's beta to broad equities means SPX trend is a shared regime tag.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="ndx_index", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="The Nasdaq-100 carries the high-beta tech/liquidity factor crypto co-moves with most strongly — a faster risk-appetite read than SPX.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="eurusd", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="EUR/USD is the dominant dollar-strength gauge; a weaker dollar loosens global financial conditions, a tailwind for risk assets.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="usdjpy", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="USD/JPY tracks the yen carry trade and global liquidity; a sharp JPY rally often coincides with cross-asset risk-off deleveraging.", transform_version="multiasset-daily-v1"),
    # --- SOCIAL AUTHORITY ("PageRank for credibility", Phase 3): score voices by whether their PREDICTIVE claims
    # came true (deterministic Brier-skill vs base rate), whether they were FIRST (primacy), and whether they LED
    # an event vs ECHOED it — weighted by a citation-graph PageRank ANCHORED to that track record. Both features
    # are POINT-IN-TIME with history (availability == observation; a real-time credibility judgement is knowable
    # only when made — no look-ahead). Derived from the Phase-0 voice timeline, not a managed network pull, so they
    # live outside the managed-ingest catalog. tier1 + low-confidence: influence ≠ authority and a loud-but-wrong
    # account scores ~0, but the feature still must EARN its place out-of-sample through the gate. ---
    FeatureDefinition(
        name="authority_weighted_claim_signal",
        source="social_authority",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass",
        prior=(
            "A credibility-weighted directional consensus [-1, +1] of recent claims on an asset: each voice's vote "
            "(up/down/flat × conviction) is weighted by its citation-graph PageRank ANCHORED to a deterministic "
            "track record (Brier-skill vs base rate), discounted for echoing vs leading. A positive shift flags "
            "credible voices turning bullish before it is priced. Influence ≠ authority — a loud, wrong account "
            "barely registers. tier1 — must earn its place via OOS."
        ),
        transform_version=AUTHORITY_TRANSFORM_VERSION,
    ),
    FeatureDefinition(
        name="author_authority",
        source="social_authority",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass",
        prior=(
            "Per-voice credibility weight (personalized PageRank over the who-cites-whom graph, teleport ∝ the "
            "deterministic Brier-skill track record). The diagnostic per-handle series feeding the weighted claim "
            "signal: a quiet calibrated voice scores high, a loud wrong one scores ~0. tier1 — must earn OOS."
        ),
        transform_version=AUTHORITY_TRANSFORM_VERSION,
    ),
    FeatureDefinition(name="pm_implied_prob", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Odds are a cross-market probability signal."),
    FeatureDefinition(name="pm_prob_velocity", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Probability repricing speed identifies changing beliefs."),
    FeatureDefinition(name="pm_book_depth", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Depth defines fillable capacity."),
    # --- EU-accessible, keyless alt-data (tier1 until validated OOS): GDELT geopolitical tone + Deribit DVOL ---
    FeatureDefinition(
        name="gdelt_tone",
        source="gdelt",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily geopolitical news tone (next-day availability floor — a day's indexed articles are closed by end-of-day; no look-ahead)",
        prior="Aggregate geopolitical/macro news tone from GDELT (keyless, global); negative tone spikes mark risk-off events that can precede drawdowns; sustained positive tone may tag risk-on regimes. tier1 — must earn its place OOS.",
        transform_version="gdelt-tone-v1",
    ),
    FeatureDefinition(
        name="dvol",
        source="deribit",
        tier="tier0",
        asset_classes=["crypto"],
        asof_semantics="daily close (next-day availability floor — DVOL bar opens at midnight UTC and is finalized at day-end; no look-ahead)",
        prior="Deribit DVOL is the crypto-native options implied volatility index (30-day annualized), the VIX equivalent for BTC/ETH options; elevated DVOL marks stress or opportunity and conditions position sizing and regime filters.",
        transform_version="dvol-v1",
    ),
    # =====================================================================================================
    # THE 10 NEW ALT-DATA SOURCES (wired additively; PIT-honest). Honest-by-design:
    #   * Genuine attention/macro signals (Wikipedia, Reddit, RSS, CryptoPanic, NFCI, jobless claims) are
    #     tier1 + low-confidence — they MUST earn their place OOS; the gate down-weights until they pay.
    #   * NON-CAUSAL CONTROLS (weather, astro ephemeris, exotic earthquakes/Kp, daily flight counts) are
    #     wired honestly so the Gate has a known-false baseline to KILL — they are NEVER expected to survive.
    #   * google_trends carries an explicit REVISION-HAZARD note: it rescales history on every re-fetch
    #     (look-ahead contamination) — REVIEW/NO-GO for backtest, paper alerting only until validated.
    # =====================================================================================================
    # --- Extended FRED macro (free, key optional; ALFRED initial-release vintages → available_at == realtime_start) ---
    FeatureDefinition(
        name="nfci",
        source="fred",
        tier="tier0",
        asof_semantics="FRED/ALFRED initial-release time (realtime_start = the actual Wednesday release; no look-ahead)",
        asset_classes=["crypto", "equity"],
        prior="Chicago Fed National Financial Conditions Index (weekly): a negative NFCI = looser-than-average financial conditions (risk-on tailwind); a sharp tightening marks stress that conditions risk premia across every asset class.",
        transform_version="nfci-alfred-v1",
    ),
    FeatureDefinition(
        name="initial_claims",
        source="fred",
        tier="tier0",
        asof_semantics="FRED/ALFRED initial-release time (realtime_start = the actual Thursday release; ~8-day ref lag; no look-ahead)",
        asset_classes=["crypto", "equity"],
        prior="US weekly initial jobless claims: a rising trend = labour-market deterioration (bearish macro), a falling trend = strength; a shared growth-regime read that conditions cross-asset risk appetite.",
        transform_version="initial-claims-alfred-v1",
    ),
    # --- Wikipedia pageviews (free, no key, immutable counts; per-symbol via entity map; available_at = T+1) ---
    FeatureDefinition(
        name="wiki_pageviews",
        source="wikimedia",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily count, available_at = obs_date + 1 day midnight UTC (Wikimedia publishes day-T on day T+1; immutable, no revision)",
        prior="Wikipedia article page-view count is a clean, free, causal crowd-attention signal (knowable T+1, never revised). An attention surge often leads price at narrative onset — low-confidence until validated OOS.",
        transform_version="wiki-pageviews-v1",
    ),
    FeatureDefinition(
        name="wiki_pageviews_log",
        source="wikimedia",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily count, available_at = obs_date + 1 day midnight UTC (immutable, no revision)",
        prior="Natural log of Wikipedia page-views — stabilizes variance across articles of vastly different scale so a fitted threshold is comparable cross-asset. Low-confidence until validated OOS.",
        transform_version="wiki-pageviews-v1",
    ),
    FeatureDefinition(
        name="wiki_pageviews_zscore",
        source="wikimedia",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily count, available_at = obs_date + 1 day midnight UTC; trailing 30d within-article z of log views (strictly causal)",
        prior="30-day trailing z-score of log Wikipedia views surfaces an attention SPIKE relative to the article's own recent baseline — a within-asset, scale-free crowd-attention shock that may precede price. Low-confidence until validated OOS.",
        transform_version="wiki-pageviews-v1",
    ),
    # --- Reddit daily volume (key-gated: REDDIT_CLIENT_ID/SECRET → empty offline; market-wide; available_at = day+1) ---
    FeatureDefinition(
        name="reddit_post_volume",
        source="reddit_volume",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily count, available_at = day AFTER the observation date (full closed day; no look-ahead)",
        prior="Daily post count across key crypto/finance subreddits (r/cryptocurrency, r/bitcoin, r/ethfinance, r/wallstreetbets, r/investing) — a crude crowd-attention BREADTH proxy; a spike may precede or lag a move (direction unknown a priori). Low-confidence; requires REDDIT_CLIENT_ID/SECRET; must earn its place OOS.",
        transform_version="reddit-volume-v1",
    ),
    FeatureDefinition(
        name="reddit_comment_volume",
        source="reddit_volume",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily count, available_at = day AFTER the observation date (full closed day; no look-ahead)",
        prior="Daily comment count across the same subreddits — an engagement-DEPTH proxy (distinct from post breadth); elevated discussion may reflect uncertainty or a catalyst. Low-confidence; requires REDDIT_CLIENT_ID/SECRET; must earn its place OOS.",
        transform_version="reddit-volume-v1",
    ),
    # --- CryptoPanic news votes (key-gated: CRYPTOPANIC_API_KEY → empty offline; per-symbol; 24h window) ---
    FeatureDefinition(
        name="cryptopanic_bullish_votes",
        source="cryptopanic",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="24h rolling window snapshot, available_at = fetch time (vote counts are mutable — captured at fetch, never rewritten)",
        prior="Positive CryptoPanic vote count on news posts mentioning the coin (24h window) — a crowd attention/optimism proxy; a bullish-vote spike may mark crowd attention preceding momentum. Low-confidence (crowd noise); requires CRYPTOPANIC_API_KEY; must earn its place OOS.",
        transform_version="cryptopanic-votes-v1",
    ),
    FeatureDefinition(
        name="cryptopanic_bearish_votes",
        source="cryptopanic",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="24h rolling window snapshot, available_at = fetch time (vote counts are mutable — captured at fetch, never rewritten)",
        prior="Negative CryptoPanic vote count on news posts mentioning the coin (24h window) — a crowd pessimism proxy; a bearish spike may anticipate a downturn. Low-confidence (crowd noise); requires CRYPTOPANIC_API_KEY; must earn its place OOS.",
        transform_version="cryptopanic-votes-v1",
    ),
    # --- RSS headline count (free, no key, LLM-free counts only; market-wide; available_at = fetch time) ---
    FeatureDefinition(
        name="rss_news_count",
        source="rss",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="trailing 24h headline count from public RSS feeds; available_at == fetch time (each item's pubDate is its own PIT marker; no look-ahead)",
        prior="Raw daily headline COUNT from public crypto/finance RSS feeds (CoinTelegraph, Decrypt, CoinDesk, news.bitcoin.com) — a news-VOLUME attention proxy (counts ≠ sentiment, LLM-free). A surge may precede or coincide with major moves. Low-confidence; must earn its place OOS.",
        transform_version="rss-news-count-v1",
    ),
    # --- Google Trends (REVISION HAZARD — rescales history; market-wide; available_at = fetch time) ---
    FeatureDefinition(
        name="gtrends_search_interest",
        source="gtrends",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="weekly Trends bucket; available_at = ACTUAL fetch time (NOT the week-end) — see revision hazard",
        prior=(
            "Google Trends retail search interest (0-100) for crypto keywords — a speculative-attention proxy. "
            "REVISION HAZARD: Trends RESCALES all historical values whenever the query window changes, so a past "
            "week's value re-fetched today differs from what was knowable then — this is silent look-ahead "
            "contamination. We stamp available_at = the actual fetch time so the store surfaces (never hides) the "
            "revision. REVIEW / likely NO-GO for backtest; acceptable only for paper alerting (each bar is a "
            "fresh current snapshot). Low-confidence — must earn OOS evidence before any live strategy."
        ),
        transform_version="gtrends-weekly-v1",
        # QUARANTINED (revision_safety): Google Trends rescales its ENTIRE historical series every time a new
        # data point is fetched (the relative index is normalised within the query window). This means a bar's
        # gtrends value as seen TODAY differs from what was knowable when that bar closed → silent look-ahead.
        # The data is still INGESTED (for future profile-source audit and paper alerting), but the Gate MUST NOT
        # use this feature in backtests until profile-source validates revision_safety = PASS. Disabling here
        # removes it from feature_names() so the lab author/spec compiler cannot reference it in live Gate runs.
        # Re-enable only after a passing profile-source audit documents revision_safety = PASS.
        enabled=False,
    ),
    # --- OpenSky daily flight count (free OSINT, thin history; market-wide; available_at = day+1) ---
    FeatureDefinition(
        name="opensky_daily_flights",
        source="opensky_daily",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily unique-aircraft count, available_at = flight_date + 1 day midnight UTC (≥1-day publication lag; no look-ahead)",
        prior=(
            "Global daily flight count (unique ICAO-24 aircraft on the free OpenSky Network) — a crude, "
            "LOW-CONFIDENCE, largely NON-CAUSAL macro economic-activity proxy ('are people flying?'). Coverage is "
            "thin (≤30-day free-tier history, rate-limited, pre-2019 unreliable). Wired honestly so the Gate can "
            "falsify it; must earn its place OOS — flag low-confidence always."
        ),
        transform_version="opensky-daily-flights-v1",
    ),
    # --- Open-Meteo weather hub stress (NON-CAUSAL control; free, no key; market-wide; available_at = obs+1) ---
    FeatureDefinition(
        name="weather_hub_stress",
        source="openmeteo",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily cross-hub stress score, available_at = obs_date + 1 day 06:00 UTC (Open-Meteo reanalysis finishes next day; no look-ahead)",
        prior=(
            "NON-CAUSAL CONTROL FEATURE — cross-hub (NYC/London/Tokyo/Shanghai) cold+wet+windy 'disruption stress' "
            "score [0,1] from the free Open-Meteo archive. Any economic-activity effect is tiny and almost certainly "
            "swamped by market structure. Wired honestly so the Gate can falsify it — VERY low confidence, never "
            "expected to survive."
        ),
        transform_version="weather-openmeteo-v1",
    ),
    # --- Deterministic astro ephemeris (NON-CAUSAL controls; stdlib-only; market-wide; available_at = day midnight UTC) ---
    FeatureDefinition(
        name="astro_lunar_phase",
        source="astro",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="deterministic per-day geometry, available_at = midnight UTC of the day (knowable at day-start; no look-ahead, no revision)",
        prior="NON-CAUSAL CONTROL FEATURE — lunar illuminated fraction [0,1] (0 = new, 1 = full). The Moon does not cause price moves; wired honestly as a known-false baseline the Gate is expected to reject.",
        transform_version="astro-ephemeris-v1",
    ),
    FeatureDefinition(
        name="astro_sun_longitude",
        source="astro",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision)",
        prior="NON-CAUSAL CONTROL FEATURE — Sun ecliptic longitude [0,360) (a calendar-season proxy). Wired honestly as a known-false baseline; the Gate is expected to reject it.",
        transform_version="astro-ephemeris-v1",
    ),
    FeatureDefinition(
        name="astro_jupiter_longitude",
        source="astro",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision)",
        prior="NON-CAUSAL CONTROL FEATURE — Jupiter ecliptic longitude [0,360) (~12-year cycle). Wired honestly as a known-false baseline; the Gate is expected to reject it.",
        transform_version="astro-ephemeris-v1",
    ),
    FeatureDefinition(
        name="astro_saturn_longitude",
        source="astro",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision)",
        prior="NON-CAUSAL CONTROL FEATURE — Saturn ecliptic longitude [0,360) (~29-year cycle). Wired honestly as a known-false baseline; the Gate is expected to reject it.",
        transform_version="astro-ephemeris-v1",
    ),
    FeatureDefinition(
        name="astro_sun_jupiter_aspect",
        source="astro",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="deterministic per-day geometry, available_at = midnight UTC of the day (no look-ahead, no revision)",
        prior="NON-CAUSAL CONTROL FEATURE — Sun-Jupiter angular separation [0,180] (0 = conjunction, 180 = opposition). Wired honestly as a known-false baseline; the Gate is expected to reject it.",
        transform_version="astro-ephemeris-v1",
    ),
    # --- Exotic ORTHOGONALITY CONTROLS (USGS earthquakes + NOAA Kp; non-causal; market-wide; Gate must kill them) ---
    FeatureDefinition(
        name="usgs_earthquake_count",
        source="usgs",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="past-24h global count; live-query available_at = as_of (snapshot); daily-batch floor = obs_day + 1 (no look-ahead)",
        prior="ORTHOGONALITY CONTROL — global earthquake event count (USGS free feed). No plausible causal path to crypto prices; a known-false baseline so the Gate has a noise floor to kill. If it ever drives a signal that is a data-snooping red flag, not an edge. Must be killed by the Gate.",
        transform_version="exotic-usgs-eq-v1",
    ),
    FeatureDefinition(
        name="usgs_max_magnitude",
        source="usgs",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="past-24h global max magnitude; live-query available_at = as_of (snapshot); gap = None, never 0",
        prior="ORTHOGONALITY CONTROL — daily maximum earthquake magnitude (USGS free feed). No plausible causal path to crypto prices; a known-false baseline. Must be killed by the Gate.",
        transform_version="exotic-usgs-eq-v1",
    ),
    FeatureDefinition(
        name="noaa_kp_index",
        source="noaa",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily-max Kp; live-query available_at = as_of (snapshot); daily-batch floor = obs_day + 1; gap = None, never 0",
        prior="ORTHOGONALITY CONTROL — NOAA planetary Kp geomagnetic index (daily max [0-9]). Geomagnetic activity has no plausible causal path to crypto prices; a known-false baseline. Must be killed by the Gate.",
        transform_version="exotic-noaa-kp-v1",
    ),
    # =====================================================================================================
    # TOOL-WAVE-A: 4 MORE FREE, NO-KEY alt-data sources (DefiLlama stablecoins, CoinGecko, BTC on-chain,
    # GDELT news-volume). All PIT-honest (daily aggregate finalized after the day closes → available_at =
    # obs_day + 1; gaps are absent/None, never zero-fabricated; degrade to [] offline). tier1 +
    # low-confidence — the Gate is the disposal layer. None of these are non-causal controls: each is a
    # genuine (if weak) liquidity/size/attention/on-chain-activity read that must EARN its place OOS.
    # NOTE: the legacy market-wide `defi_tvl` (DefiLlamaTvlProvider) is already registered above — this wave
    # ADDS only the orthogonal total-stablecoin-mcap metric, never re-registers defi_tvl.
    # =====================================================================================================
    # --- DefiLlama total stablecoin market cap (free, no key, market-wide; available_at = obs_day + 1) ---
    FeatureDefinition(
        name="stablecoin_mcap",
        source="defillama",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily total, available_at = obs_day + 1 day (a daily aggregate is finalized after the day closes; knowable T+1; no look-ahead). DefiLlama may re-state very recent days as chains re-sync — surfaced via the append-only store, never hidden.",
        prior="Total circulating stablecoin market cap is crypto's dry powder: a growing float is fiat waiting to deploy (risk-on fuel), a shrinking float is capital redeeming out of crypto (risk-off). Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="defillama-daily-v1",
    ),
    # --- CoinGecko (free public tier, no key): per-coin mcap + 24h volume (T+1) + market-wide BTC dominance ---
    FeatureDefinition(
        name="cg_market_cap",
        source="coingecko",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily per-coin market cap, available_at = obs_day + 1 day (daily aggregate finalized after day close; knowable T+1; no look-ahead). CoinGecko may re-state very recent days — surfaced via the append-only store, never hidden.",
        prior="A coin's market cap is its float-weighted size; large relative moves track capital rotating in/out of the asset. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="coingecko-daily-v1",
    ),
    FeatureDefinition(
        name="cg_total_volume",
        source="coingecko",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily per-coin 24h total volume, available_at = obs_day + 1 day (daily aggregate finalized after day close; knowable T+1; no look-ahead). CoinGecko may re-state very recent days — surfaced via the append-only store, never hidden.",
        prior="A coin's 24h total traded volume proxies attention / conviction; a volume spike often accompanies the onset of a move. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="coingecko-daily-v1",
    ),
    FeatureDefinition(
        name="cg_btc_dominance",
        source="coingecko",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="CURRENT snapshot from /global, available_at = fetch time (we only knew it when we pulled it — honest, never back-dated; no look-ahead). A single point per pass.",
        prior="BTC dominance (BTC's share of total crypto mcap) is a risk-rotation gauge: falling dominance is capital rotating into alts (risk-on within crypto), rising dominance is a flight to BTC. Low-confidence until validated OOS.",
        transform_version="coingecko-daily-v1",
    ),
    # --- blockchain.com BTC on-chain fundamentals (free, no key, market-wide; available_at = obs_day + 1) ---
    FeatureDefinition(
        name="btc_hashrate",
        source="blockchain.com",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily on-chain level, available_at = obs_day + 1 day midnight UTC (blockchain.com publishes a full UTC day with ≥~1-day latency; no look-ahead). Recent points may be revised slightly as late blocks settle — the 1-day lag absorbs it.",
        prior="Estimated Bitcoin network hash rate measures REAL economic activity on the chain (miner commitment) — an orthogonal axis to price/funding/sentiment. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="onchain-blockchain-v1",
    ),
    FeatureDefinition(
        name="btc_tx_count",
        source="blockchain.com",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily on-chain count, available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Recent points may be revised slightly as late blocks settle.",
        prior="Confirmed Bitcoin transactions per day is a real on-chain economic-activity read; rising transactions can reflect organic demand — orthogonal to price/funding/sentiment. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="onchain-blockchain-v1",
    ),
    FeatureDefinition(
        name="btc_mempool_size",
        source="blockchain.com",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily on-chain level (bytes), available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Recent points may be revised slightly as late blocks settle.",
        prior="Bitcoin mempool size (bytes of unconfirmed transactions) reflects on-chain fee pressure / congestion — a real-activity read orthogonal to price/funding/sentiment. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="onchain-blockchain-v1",
    ),
    FeatureDefinition(
        name="btc_active_addresses",
        source="blockchain.com",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily on-chain count, available_at = obs_day + 1 day midnight UTC (≥~1-day publication lag; no look-ahead). Recent points may be revised slightly as late blocks settle.",
        prior="Unique active Bitcoin addresses per day is a network-adoption / organic-demand read on real on-chain activity — orthogonal to price/funding/sentiment. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="onchain-blockchain-v1",
    ),
    # --- GDELT 2.0 daily NEWS-VOLUME count (free, no key, LLM-free counts only; per-symbol; available_at = obs_day + 1) ---
    # Distinct from the existing market-wide `gdelt_tone` (provider "gdelt"): this is per-topic raw article
    # COUNTS (an attention/coverage axis), stored under the separate "gdelt_counts" provider bucket.
    FeatureDefinition(
        name="gdelt_news_volume",
        source="gdelt_counts",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="daily per-topic article count, available_at = obs_day + 1 day midnight UTC (a full UTC day's count is complete only after the day closes; no look-ahead). A GDELT outage is unknown coverage (None), not zero articles.",
        prior="GDELT daily news-VOLUME count (number of global articles mentioning a topic) is a cheap, free, LLM-free attention/coverage proxy; a coverage surge often coincides with or slightly leads a narrative-driven move. COUNTS ONLY (tone deliberately closed — see gdelt_tone for tone). Low-confidence until validated OOS.",
        transform_version="gdelt-counts-v1",
    ),
    # =====================================================================================================
    # TOOL-WAVE-C: 2 MORE FREE, NO-KEY alt-data FLOW sources (FRED keyless macro-liquidity, DefiLlama
    # stablecoin flow). Both PIT-honest and degrade to [] offline. tier1 + low-confidence — the Gate is the
    # disposal layer. Neither is a non-causal control: each is a genuine (if weak) macro/on-chain LIQUIDITY
    # read that must EARN its place OOS. These add the FLOW (the derivative) where prior waves added the
    # LEVEL: orthogonal to defi_tvl / stablecoin_mcap and to the FRED macro_regime/rate metrics.
    # REVISION HONESTY: the FRED keyless fredgraph.csv carries NO vintage column, so available_at is a
    # CONSERVATIVE ~8-day H.4.1 publication-lag floor (under-claims availability, never over-claims — the
    # ALFRED initial-release path in macro_extra is the vintage-exact seam). DefiLlama may re-state very
    # recent days as chains re-sync — the +1d floor + the append-only store surface revisions, never hide them.
    # =====================================================================================================
    # --- FRED keyless macro-liquidity (free, no key, market-wide; available_at = obs_day + ~8 days) ---
    FeatureDefinition(
        name="fed_balance_sheet_usd",
        source="fred",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="weekly H.4.1 reference (Wednesday), available_at = ts + 8 days (CONSERVATIVE publication-lag floor; the keyless fredgraph.csv has no vintage column so we under-claim availability rather than risk look-ahead). A missing/'.' value is absent, never zero-fabricated.",
        prior="Total Federal Reserve assets (WALCL) are the base money supply: balance-sheet EXPANSION (QE) pumps liquidity into the system (risk-on), CONTRACTION (QT) drains it — a first-order macro driver of risk-asset beta. Free, weekly, knowable ~T+8. Low-confidence until validated OOS.",
        transform_version="macro-liquidity-v1",
    ),
    FeatureDefinition(
        name="net_liquidity_usd",
        source="fred",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="weekly H.4.1 reference (Wednesday), available_at = ts + 8 days (CONSERVATIVE publication-lag floor; keyless CSV has no vintage column). A date is absent whenever EITHER WALCL or WTREGEN is missing — no fabricated difference.",
        prior="Net liquidity = Fed total assets (WALCL) minus the Treasury General Account (WTREGEN, cash drained from the banking system): a rising TGA sterilizes balance-sheet liquidity, a falling TGA releases it. The widely-watched WALCL - TGA proxy has historically tracked risk-asset beta — an orthogonal macro-plumbing read. Free, weekly, knowable ~T+8. Low-confidence until validated OOS.",
        transform_version="macro-liquidity-v1",
    ),
    # --- DefiLlama stablecoin FLOW + chain-split (free, no key, market-wide; available_at = obs_day + 1) ---
    FeatureDefinition(
        name="stablecoin_net_flow_usd",
        source="defillama",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="signed day-over-day mcap delta, available_at = obs_day + 1 day (a daily aggregate is finalized after the UTC day closes; knowable T+1; no look-ahead). A flow point is ABSENT across a missing day — no delta invented across a gap. DefiLlama may re-state recent days — surfaced via the append-only store.",
        prior="Net daily stablecoin minting (today's total float minus yesterday's) is fresh fiat ENTERING crypto when positive (risk-on fuel) and capital REDEEMING out when negative. The flow leads the level: the derivative flips sign before the slow-moving market-cap level moves. Orthogonal to the level series stablecoin_mcap. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="stablecoin-flows-v1",
    ),
    FeatureDefinition(
        name="stablecoin_eth_share",
        source="defillama",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="fraction of total float on Ethereum [0,1], available_at = obs_day + 1 day (daily aggregate finalized after day close; knowable T+1; no look-ahead). Absent whenever either the all-chain or Ethereum total is missing for that day — never fabricated.",
        prior="Share of total stablecoin float that sits on Ethereum: a falling ETH share is float rotating to cheaper / higher-throughput chains (a risk-appetite + chain-rotation read); a rising share is consolidation back onto the settlement layer. Free, daily, knowable T+1. Low-confidence until validated OOS.",
        transform_version="stablecoin-flows-v1",
    ),
)


def feature_names() -> set[str]:
    return {feature.name for feature in FEATURE_REGISTRY if feature.enabled}


def registry_version() -> str:
    """A deterministic 16-char content hash of the ENABLED feature registry — each feature's (name, source,
    transform_version). Pinned into a promotion's freeze so a survivor stays reproducible: if a feature's source
    or frozen transform later changes, this hash changes and the live lane can flag that the strategy is no longer
    running against the registry it was proven on. Keyless/offline (sha256), stable across processes."""
    import hashlib

    payload = ";".join(
        f"{f.name}|{f.source}|{f.transform_version or ''}"
        for f in sorted((f for f in FEATURE_REGISTRY if f.enabled), key=lambda f: f.name)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def features_for(asset_classes: list[str]) -> list[FeatureDefinition]:
    wanted = set(asset_classes)
    return [
        feature
        for feature in FEATURE_REGISTRY
        if feature.enabled and (wanted & set(feature.asset_classes))
    ]

