# intent: define the named feature vocabulary the lab agent may reference; inputs: config/static seed; outputs: FeatureDefinition list; invariants: every feature has as-of semantics and a prior hypothesis.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Pinned transform version for the xAI/Grok Twitter sentiment source.  Bump this string whenever
# the scoring prompt or weighting logic changes so a gate-passed survivor remains re-runnable.
TWITTER_TRANSFORM_VERSION = "xai-twitter-sentiment-v1"


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
    FeatureDefinition(name="xasset_risk_appetite", source="ccxt", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="exchange publication time", prior="Crypto perp funding is a fast, 24/7 read on speculative risk appetite that leads slower equity/macro signals — transfer crypto's read onto equities.", transform_version="xasset-funding-v1"),
    FeatureDefinition(name="macro_regime", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Macro regime (curve slope, real rates, liquidity) conditions risk premia across every asset class — a shared regime tag, not a single-market signal.", transform_version="macro-regime-v1"),
    FeatureDefinition(name="vix_level", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="VIX measures implied volatility; extremes signal regime shifts and mean-revert at swing horizon", transform_version="vix-level-v1"),
    FeatureDefinition(name="fed_funds_rate", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Federal funds rate changes drive risk premia across all asset classes", transform_version="fed-funds-v1"),
    FeatureDefinition(name="defi_tvl", source="defillama", tier="tier0", asset_classes=["crypto"], asof_semantics="daily publication time (next-day availability floor)", prior="DeFi TVL flows indicate risk appetite and liquidity across crypto protocols", transform_version="defi-tvl-v1"),
    FeatureDefinition(name="open_interest", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="OI changes reveal leverage build-up."),
    FeatureDefinition(name="perp_spot_basis", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Basis captures risk appetite and carry."),
    FeatureDefinition(name="exchange_netflow", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="provider knowledge time", prior="Net inflows can precede sell pressure."),
    FeatureDefinition(name="vix_term_slope", source="fred/cboe", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Term slope encodes risk regime."),
    FeatureDefinition(name="putcall_ratio", source="cboe", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time (next-day availability floor)", prior="Sentiment extremes mean-revert at swing horizon.", transform_version="putcall-zscore-v1"),
    FeatureDefinition(name="liquidation_cascade", source="coinglass", tier="tier0", asset_classes=["crypto"], asof_semantics="liquidation bucket close time (next-bucket availability floor)", prior="A spike in total long+short liquidations marks forced deleveraging that overshoots — a cascade exhausts sellers and mean-reverts at the swing horizon.", transform_version="liquidation-cascade-zscore-v1"),
    # Best-effort OSINT ("watching planes"): aircraft activity from the free OpenSky Network as a crude,
    # LOW-CONFIDENCE macro-risk-appetite proxy. Availability == observation time (a live snapshot is only
    # knowable when taken — no look-ahead). tier1 + the explicit low-confidence prior mean it must earn its
    # place via out-of-sample; the gate down-weights it until it pays.
    FeatureDefinition(name="osint_air_activity", source="opensky", tier="tier1", asset_classes=["crypto", "equity"], asof_semantics="live ADS-B snapshot time (availability == observation, no look-ahead)", prior="Aircraft activity is a crude, low-confidence macro risk-appetite/economic-activity proxy (best-effort OSINT); must earn its place via OOS — flag low-confidence.", transform_version="osint-adsb-v1"),
    FeatureDefinition(name="cftc_net_positioning", source="cftc", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="CFTC release time", prior="Crowded positioning can unwind."),
    FeatureDefinition(name="dxy", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Dollar strength changes risk appetite."),
    FeatureDefinition(name="yield_curve_2s10s", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Curve slope tracks macro regime."),
    FeatureDefinition(name="credit_spread", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Credit stress drives equity risk premia."),
    FeatureDefinition(name="days_to_earnings", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="Earnings windows alter drift and volatility."),
    FeatureDefinition(name="insider_buy_ratio", source="sec_edgar", tier="tier0", asset_classes=["equity"], asof_semantics="Form 4 publication time", prior="Insider buying can signal undervaluation."),
    FeatureDefinition(name="short_interest_ratio", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="High short interest can fuel squeezes."),
    FeatureDefinition(name="ret_Nd", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity", "prediction"], asof_semantics="bar close time", prior="Medium-term return captures momentum/reversal."),
    FeatureDefinition(name="atr", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ATR normalizes risk and stop distance."),
    FeatureDefinition(name="rsi", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="RSI captures overextension."),
    FeatureDefinition(name="adx", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ADX separates trend from chop."),
    FeatureDefinition(name="bb_z", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Band z-score captures statistically unusual price."),
    FeatureDefinition(name="vol_realized", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Realized vol gates capacity and risk."),
    # --- social feeds (tier1, low-confidence until validated OOS): Reddit crowd sentiment (free, no key) and
    # LunarCrush social metrics (key-gated; empty without a key). The gate down-weights tier1 until it pays. ---
    FeatureDefinition(name="reddit_sentiment", source="reddit", tier="tier1", asset_classes=["crypto"], asof_semantics="public hot.json read time (availability == observation, no look-ahead)", prior="Reddit crowd chatter (bull vs bear post mix) is a fast, low-confidence sentiment proxy — extremes may mean-revert at the swing horizon; must earn its place via OOS.", transform_version="reddit-sentiment-v1"),
    FeatureDefinition(name="social_volume", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="A surge in social volume can mark crowd attention that precedes (or exhausts) a move — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="social_sentiment", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush social sentiment is a crowd-mood proxy; a positive shift may precede continuation before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="galaxy_score", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush Galaxy Score blends price + social health into one rank; extremes are a low-confidence regime tag — must earn its place via OOS.", transform_version="lunarcrush-v1"),
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
    FeatureDefinition(name="pm_implied_prob", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Odds are a cross-market probability signal."),
    FeatureDefinition(name="pm_prob_velocity", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Probability repricing speed identifies changing beliefs."),
    FeatureDefinition(name="pm_book_depth", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Depth defines fillable capacity."),
)


def feature_names() -> set[str]:
    return {feature.name for feature in FEATURE_REGISTRY if feature.enabled}


def features_for(asset_classes: list[str]) -> list[FeatureDefinition]:
    wanted = set(asset_classes)
    return [
        feature
        for feature in FEATURE_REGISTRY
        if feature.enabled and (wanted & set(feature.asset_classes))
    ]

