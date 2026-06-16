# intent: a PLUGGABLE DataSourceRegistry — a typed DataSource protocol (name, kind, point-in-time
# query(scope, as_of)->SourceFeature, declared prior, transform_version, confidence) plus a registry so any
# agent can discover/query a source by NAME. This is a THIN ADAPTER over the existing providers in
# cosmu/data/altdata.py (funding/fear_greed/news/fred/polymarket/coinglass/cboe), NOT a rewrite — it wraps
# the AltDataProvider/NewsProvider seams. Invariants: every query is point-in-time (returns the latest value
# whose available_at <= as_of, never look-ahead), every source declares a prior + transform_version +
# confidence so a low-confidence OSINT source must earn its place via OOS, and no LLM is ever on this path.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from cosmu.data.altdata import AltDataProvider, NewsProvider, rolling_zscore
from cosmu.ingest.standardize import standardize_news

SourceKind = Literal["price", "social", "sentiment", "macro", "derivatives", "odds", "osint"]


@dataclass(frozen=True)
class SourceFeature:
    """One point-in-time observation of a named source feature.

    `value` is the latest reading whose `available_at <= as_of` (None if nothing was knowable yet).
    `confidence` in [0,1] is the source's DECLARED self-assessment — low-confidence OSINT must earn
    its place via out-of-sample, so the gate can flag/weight it. Never look-ahead.

    `observed_ts` is the source's TRUE observation timestamp (when the reading describes), distinct from
    `available_at` (when we could first know it). They differ by the availability lag — e.g. a daily count
    observed on day T is only available_at = T+1. Optional + backward-compatible: when a source cannot
    distinguish the two it leaves this None and the consumer falls back to `available_at`.
    """

    name: str
    scope: str  # the symbol or "MARKET" for market-wide series
    as_of: datetime
    value: float | None
    available_at: datetime | None
    confidence: float
    transform_version: str | None
    prior: str
    low_confidence: bool = False
    observed_ts: datetime | None = None


@runtime_checkable
class DataSource(Protocol):
    """The seam any agent discovers + queries by name. Wraps an underlying provider; stays point-in-time."""

    name: str
    kind: SourceKind
    metric: str
    prior: str
    transform_version: str | None
    confidence: float

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest value of this source for `scope` knowable at `as_of` (point-in-time, no look-ahead)."""


@dataclass
class AltMetricSource:
    """Adapts an existing AltDataProvider metric (funding_rate / fear_greed / risk_on / macro_regime /
    liquidations / putcall_ratio / OSINT) into a named, point-in-time DataSource. The provider already
    stamps availability; this layer only selects the latest value <= as_of and attaches the declared prior."""

    name: str
    kind: SourceKind
    metric: str
    prior: str
    provider: AltDataProvider
    transform_version: str | None = None
    confidence: float = 1.0
    market_wide: bool = False

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        key = "MARKET" if self.market_wide else scope
        points = self.provider.fetch_series(key, self.metric, limit=limit)
        latest = None
        for p in sorted(points, key=lambda x: x.available_at):
            if p.available_at <= as_of:
                latest = p
            else:
                break
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


@dataclass
class NewsSentimentSource:
    """Adapts a NewsProvider into a named numeric SENTIMENT source, standardized ONCE via the deterministic
    offline lexicon (the LLM seam lives in ingest/standardize, never on this query path). Point-in-time."""

    name: str
    prior: str
    provider: NewsProvider
    transform_version: str | None = "news-sentiment-v1"
    confidence: float = 0.6
    kind: SourceKind = "sentiment"
    metric: str = "news_sentiment"

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        items = self.provider.fetch_news(scope, limit=limit)
        points = standardize_news(items)  # deterministic lexicon, content-hash cached, no LLM
        latest = None
        for p in sorted(points, key=lambda x: x.available_at):
            if p.available_at <= as_of:
                latest = p
            else:
                break
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


class DataSourceRegistry:
    """Discover + query data sources by name. The seam to add/upgrade sources later without touching callers."""

    def __init__(self) -> None:
        self._sources: dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        if not isinstance(source, DataSource):
            raise TypeError(f"{source!r} does not satisfy the DataSource protocol")
        self._sources[source.name] = source

    def get(self, name: str) -> DataSource:
        return self._sources[name]

    def names(self) -> list[str]:
        return sorted(self._sources)

    def discover(self) -> list[dict[str, object]]:
        """A machine-readable catalog any agent can read to decide which source to query."""
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "metric": s.metric,
                "prior": s.prior,
                "transform_version": s.transform_version,
                "confidence": s.confidence,
                "low_confidence": s.confidence < 0.5,
            }
            for s in sorted(self._sources.values(), key=lambda x: x.name)
        ]

    def query(self, name: str, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        return self._sources[name].query(scope, as_of, limit=limit)


def default_source_registry(
    *,
    alt_provider: AltDataProvider | None = None,
    news_provider: NewsProvider | None = None,
    include_osint: bool = True,
) -> DataSourceRegistry:
    """Wrap the existing free providers under one named registry. Providers are INJECTED so tests run
    offline on fixtures; absent providers simply mean that source is not registered (LLM/network-optional)."""
    from cosmu.data.altdata import FearGreedProvider, FundingRateProvider

    reg = DataSourceRegistry()
    alt = alt_provider
    if alt is None:
        # Live, free, no-key numeric providers (point-in-time stamped inside each provider).
        funding = FundingRateProvider()
        feargreed = FearGreedProvider()
        reg.register(AltMetricSource("funding_rate", "derivatives", "funding_rate", "Funding extremes proxy crowded leverage; a long filter.", funding, transform_version="funding-zscore-v1", confidence=0.9))
        reg.register(AltMetricSource("fear_greed", "sentiment", "fear_greed", "Crowd fear mean-reverts at swing horizon.", feargreed, transform_version="feargreed-regime-v1", confidence=0.8, market_wide=True))
    else:
        reg.register(AltMetricSource("funding_rate", "derivatives", "funding_rate", "Funding extremes proxy crowded leverage; a long filter.", alt, transform_version="funding-zscore-v1", confidence=0.9))
        reg.register(AltMetricSource("fear_greed", "sentiment", "fear_greed", "Crowd fear mean-reverts at swing horizon.", alt, transform_version="feargreed-regime-v1", confidence=0.8, market_wide=True))
        reg.register(AltMetricSource("pm_risk_on", "odds", "risk_on", "Prediction-market odds price the risk regime before any single asset.", alt, transform_version="pm-riskon-v1", confidence=0.7, market_wide=True))
        reg.register(AltMetricSource("macro_regime", "macro", "macro_regime", "Macro regime conditions risk premia across every class.", alt, transform_version="macro-regime-v1", confidence=0.8, market_wide=True))

    if news_provider is not None:
        reg.register(NewsSentimentSource("news_sentiment", "A positive news-flow shift precedes multi-day continuation before it is fully priced.", news_provider))

    if include_osint:
        from cosmu.data.sources.osint_adsb import AdsbDataSource

        reg.register(AdsbDataSource())

    # The 10 new alt-data sources, registered by name so any agent can discover + PIT-query them. Each is
    # self-contained, offline-safe (network/key failure → None value, never a crash), and carries its own
    # declared prior + transform_version + confidence. Non-causal controls (weather/astro/exotic/flights)
    # are flagged low-confidence so the gate down-weights / kills them. Additive — existing registrations
    # are untouched.
    from cosmu.data.sources.astro_ephemeris import make_astro_sources
    from cosmu.data.sources.cryptopanic import (
        CryptoPanicBearishVotesSource,
        CryptoPanicBullishVotesSource,
    )
    from cosmu.data.sources.exotic_controls import (
        NoaaKpIndexSource,
        UsgsEarthquakeSource,
        UsgsMaxMagnitudeSource,
    )
    from cosmu.data.sources.google_trends import GoogleTrendsSource
    from cosmu.data.sources.osint_opensky_daily import OpenSkyDailyFlightsSource
    from cosmu.data.sources.reddit_volume import (
        RedditCommentVolumeDataSource,
        RedditVolumeDataSource,
    )
    from cosmu.data.sources.rss_news import RssNewsCountSource
    from cosmu.data.sources.weather_openmeteo import WeatherOpenMeteoSource
    from cosmu.data.sources.wikipedia_pageviews import WikipediaPageviewsSource

    reg.register(WeatherOpenMeteoSource())
    reg.register(OpenSkyDailyFlightsSource())
    reg.register(RssNewsCountSource())
    reg.register(GoogleTrendsSource())
    reg.register(RedditVolumeDataSource())
    reg.register(RedditCommentVolumeDataSource())
    reg.register(CryptoPanicBullishVotesSource())
    reg.register(CryptoPanicBearishVotesSource())
    for metric in ("wiki_pageviews", "wiki_pageviews_log", "wiki_pageviews_zscore"):
        wiki = WikipediaPageviewsSource(metric=metric)
        # The class hard-codes name="wiki_pageviews"; the metric is what distinguishes the derived series.
        # Register each under its metric so the three are discoverable as distinct named features (the
        # SourceFeature it returns also carries this name — consistent with the feature_registry keys).
        wiki.name = metric
        reg.register(wiki)
    for src in make_astro_sources():
        reg.register(src)
    reg.register(UsgsEarthquakeSource())
    reg.register(UsgsMaxMagnitudeSource())
    reg.register(NoaaKpIndexSource())

    # TOOL-WAVE-A: 4 more free, no-key named DataSources (discoverable + PIT-queryable by name). Each is
    # self-contained + offline-safe (network/shape failure → None value, never a crash), carries its own
    # declared prior + transform_version + confidence, and degrades to [] offline. All daily aggregates are
    # knowable only T+1 (no look-ahead); BTC dominance is an honest current snapshot. Additive — existing
    # registrations are untouched. make_defillama_sources() adds BOTH the legacy-equivalent defi_tvl AND the
    # new stablecoin_mcap as discoverable named sources (neither was previously registered HERE).
    from cosmu.data.sources.coingecko import make_coingecko_sources
    from cosmu.data.sources.defillama import make_defillama_sources
    from cosmu.data.sources.gdelt_counts import GdeltCountsSource
    from cosmu.data.sources.onchain_blockchain import make_onchain_blockchain_sources

    for src in make_defillama_sources():
        reg.register(src)
    for src in make_coingecko_sources():
        reg.register(src)
    for src in make_onchain_blockchain_sources():
        reg.register(src)
    reg.register(GdeltCountsSource())

    # TOOL-WAVE-C: 2 more free, no-key market-wide FLOW sources (discoverable + PIT-queryable by name). Each
    # is self-contained + offline-safe (network/shape failure → None value, never a crash), carries its own
    # declared prior + transform_version + confidence, and degrades to [] offline. FRED keyless macro-liquidity
    # (fed_balance_sheet_usd / net_liquidity_usd, knowable ~T+8) + DefiLlama stablecoin FLOW (the day-over-day
    # CHANGE + ETH chain-share, knowable T+1) — both orthogonal to the LEVEL series already registered. Additive.
    from cosmu.data.sources.etf_flows import make_etf_flow_sources
    from cosmu.data.sources.stablecoin_flows import make_stablecoin_flow_sources

    for src in make_etf_flow_sources():
        reg.register(src)
    for src in make_stablecoin_flow_sources():
        reg.register(src)

    return reg


__all__ = [
    "AltMetricSource",
    "DataSource",
    "DataSourceRegistry",
    "NewsSentimentSource",
    "SourceFeature",
    "SourceKind",
    "default_source_registry",
    "rolling_zscore",
]
