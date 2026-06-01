# intent: a PLUGGABLE DataSourceRegistry — a typed DataSource protocol (name, kind, point-in-time
# query(scope, as_of)->SourceFeature, declared prior, transform_version, confidence) plus a registry so any
# agent can discover/query a source by NAME. This is a THIN ADAPTER over the existing providers in
# cosmu/data/altdata.py (funding/fear_greed/news/fred/polymarket/coinglass/cboe), NOT a rewrite — it wraps
# the AltDataProvider/NewsProvider seams. Invariants: every query is point-in-time (returns the latest value
# whose available_at <= as_of, never look-ahead), every source declares a prior + transform_version +
# confidence so a low-confidence OSINT source must earn its place via OOS, and no LLM is ever on this path.

from __future__ import annotations

from dataclasses import dataclass, field
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
