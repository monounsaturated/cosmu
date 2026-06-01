# intent: define the named feature vocabulary the lab agent may reference; inputs: config/static seed; outputs: FeatureDefinition list; invariants: every feature has as-of semantics and a prior hypothesis.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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
    FeatureDefinition(name="open_interest", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="OI changes reveal leverage build-up."),
    FeatureDefinition(name="perp_spot_basis", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Basis captures risk appetite and carry."),
    FeatureDefinition(name="exchange_netflow", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="provider knowledge time", prior="Net inflows can precede sell pressure."),
    FeatureDefinition(name="vix_term_slope", source="fred/cboe", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Term slope encodes risk regime."),
    FeatureDefinition(name="putcall_ratio", source="cboe", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Sentiment extremes mean-revert at swing horizon."),
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

