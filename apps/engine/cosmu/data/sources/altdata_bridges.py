# intent: thin AltDataProvider bridges that adapt the new query()-only DataSources (weather, opensky-daily,
# rss, wikipedia, google-trends, cryptopanic, exotic controls) onto the `fetch_series(symbol, metric, *, limit)`
# protocol the managed-ingest catalog composes. This is the SAME bridge pattern as
# providers/news.OsintAirActivityProvider: a snapshot DataSource's query() result is turned into a single
# point-in-time AltDataPoint so `ingest_numeric` / `ingest_market_wide_numeric` can store it.
#
# Invariants:
#   - Point-in-time: each bridge calls the underlying source's query(scope, as_of=now) and uses the source's
#     OWN available_at (never look-ahead). A None value (honest gap) yields [] — never a fabricated 0.
#   - Degrade gracefully: every bridge is wrapped in try/except so a dead source / missing key returns []
#     (one dead source never aborts an ingest pass). Key-gated sources (cryptopanic) return [] without a key.
#   - These bridges do NOT re-implement any fetch logic — they delegate to the concrete DataSource.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.data.providers._types import AltDataPoint

# Source-native metric name (the kwarg each DataSource is constructed with / queries) → keep DRY by reading
# it off the source instance when present.


def _snapshot(source, scope: str) -> list[AltDataPoint]:
    """Query a DataSource once at now() and wrap a non-None reading as one point-in-time AltDataPoint.

    Uses the source's OWN available_at (no look-ahead). A None value (gap) or any error → [] (honest no-data).
    """
    try:
        now = datetime.now(tz=UTC)
        feat = source.query(scope, now)
    except Exception:  # noqa: BLE001 — one dead source never aborts the pass
        return []
    if feat is None or feat.value is None:
        return []
    available_at = feat.available_at or now
    return [AltDataPoint(ts=available_at, available_at=available_at, value=float(feat.value))]


class WeatherOpenMeteoIngestProvider:
    """fetch_series bridge for WeatherOpenMeteoSource (metric=weather_hub_stress, market-wide)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "weather_hub_stress":
            return []
        from cosmu.data.sources.weather_openmeteo import WeatherOpenMeteoSource

        return _snapshot(WeatherOpenMeteoSource(offline=self.offline), "MARKET")


class OpenSkyDailyIngestProvider:
    """fetch_series bridge for OpenSkyDailyFlightsSource (metric=opensky_daily_flights, market-wide)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "opensky_daily_flights":
            return []
        from cosmu.data.sources.osint_opensky_daily import OpenSkyDailyFlightsSource

        return _snapshot(OpenSkyDailyFlightsSource(offline=self.offline), "MARKET")


class RssNewsIngestProvider:
    """fetch_series bridge for RssNewsCountSource (metric=rss_news_count, market-wide headline count)."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "rss_news_count":
            return []
        from cosmu.data.sources.rss_news import RssNewsCountSource

        return _snapshot(RssNewsCountSource(offline=self.offline), "MARKET")


class WikipediaPageviewsIngestProvider:
    """fetch_series bridge for WikipediaPageviewsSource. Per-symbol; metric selects the derived series
    (wiki_pageviews / wiki_pageviews_log / wiki_pageviews_zscore)."""

    _METRICS = ("wiki_pageviews", "wiki_pageviews_log", "wiki_pageviews_zscore")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in self._METRICS:
            return []
        from cosmu.data.sources.wikipedia_pageviews import WikipediaPageviewsSource

        return _snapshot(WikipediaPageviewsSource(metric=metric), symbol)


class GoogleTrendsIngestProvider:
    """fetch_series bridge for GoogleTrendsSource (metric=gtrends_search_interest, market-wide). Degrades to
    [] when pytrends is absent or the fetch fails (the source's own query() already swallows errors)."""

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "gtrends_search_interest":
            return []
        try:
            from cosmu.data.sources.google_trends import GoogleTrendsSource

            src = GoogleTrendsSource()
        except Exception:  # noqa: BLE001 — missing pytrends etc. → honest no-data
            return []
        return _snapshot(src, "MARKET")


class CryptoPanicIngestProvider:
    """fetch_series bridge for the CryptoPanic vote sources. Per-symbol; metric selects bullish/bearish.
    KEY-GATED: without CRYPTOPANIC_API_KEY the underlying provider returns [] (honest degradation)."""

    _METRICS = ("cryptopanic_bullish_votes", "cryptopanic_bearish_votes")

    def __init__(self, api_key: str = "", *, offline: bool = False) -> None:
        self.api_key = api_key
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in self._METRICS:
            return []
        from cosmu.data.sources.cryptopanic import (
            CryptoPanicBearishVotesSource,
            CryptoPanicBullishVotesSource,
            CryptoPanicProvider,
        )

        provider = CryptoPanicProvider(api_key=self.api_key, offline=self.offline)
        src = (
            CryptoPanicBullishVotesSource(provider=provider)
            if metric == "cryptopanic_bullish_votes"
            else CryptoPanicBearishVotesSource(provider=provider)
        )
        return _snapshot(src, symbol)


class DefiLlamaStablecoinIngestProvider:
    """fetch_series bridge for DefiLlamaSource(metric=stablecoin_mcap, market-wide). Free, no key.

    The legacy defi_tvl stays on its own provider (data/providers/onchain.DefiLlamaTvlProvider); this bridge
    ONLY adds the new total-stablecoin-mcap metric the newer DefiLlamaSource owns."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "stablecoin_mcap":
            return []
        from cosmu.data.sources.defillama import DefiLlamaSource

        return _snapshot(DefiLlamaSource(metric="stablecoin_mcap"), "MARKET")


class CoinGeckoIngestProvider:
    """fetch_series bridge for CoinGeckoSource. Free public tier, no key. Per-coin (cg_market_cap /
    cg_total_volume — scope is the symbol) + one market-wide read (cg_btc_dominance → scope MARKET)."""

    _PER_COIN = ("cg_market_cap", "cg_total_volume")
    _MARKET_WIDE = ("cg_btc_dominance",)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in self._PER_COIN and metric not in self._MARKET_WIDE:
            return []
        from cosmu.data.sources.coingecko import CoinGeckoSource

        scope = "MARKET" if metric in self._MARKET_WIDE else symbol
        return _snapshot(CoinGeckoSource(metric=metric), scope)


class OnchainBlockchainIngestProvider:
    """fetch_series bridge for OnchainBlockchainSource (blockchain.com BTC on-chain fundamentals). Free, no
    key. Market-wide (each metric describes the whole BTC network — scope MARKET)."""

    _METRICS = ("btc_hashrate", "btc_tx_count", "btc_mempool_size", "btc_active_addresses")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in self._METRICS:
            return []
        from cosmu.data.sources.onchain_blockchain import OnchainBlockchainSource

        return _snapshot(OnchainBlockchainSource(metric=metric), "MARKET")


class GdeltCountsIngestProvider:
    """fetch_series bridge for GdeltCountsSource (GDELT 2.0 daily news-VOLUME counts). Free, no key.
    Per-symbol (the topic query is resolved from the symbol — scope is the symbol; counts ≠ tone)."""

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "gdelt_news_volume":
            return []
        from cosmu.data.sources.gdelt_counts import GdeltCountsSource

        return _snapshot(GdeltCountsSource(), symbol)


class ExoticControlsIngestProvider:
    """fetch_series bridge for the exotic orthogonality-control sources (USGS earthquake count + max
    magnitude, NOAA Kp). Market-wide; metric selects which control. Non-causal — wired honestly so the
    Gate can kill them (a known-false baseline)."""

    _METRICS = ("usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index")

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in self._METRICS:
            return []
        from cosmu.data.sources.exotic_controls import (
            NoaaKpIndexSource,
            UsgsEarthquakeSource,
            UsgsMaxMagnitudeSource,
        )

        if metric == "usgs_earthquake_count":
            src = UsgsEarthquakeSource(offline=self.offline)
        elif metric == "usgs_max_magnitude":
            src = UsgsMaxMagnitudeSource(offline=self.offline)
        else:
            src = NoaaKpIndexSource(offline=self.offline)
        return _snapshot(src, "MARKET")


__all__ = [
    "CoinGeckoIngestProvider",
    "CryptoPanicIngestProvider",
    "DefiLlamaStablecoinIngestProvider",
    "ExoticControlsIngestProvider",
    "GdeltCountsIngestProvider",
    "GoogleTrendsIngestProvider",
    "OnchainBlockchainIngestProvider",
    "OpenSkyDailyIngestProvider",
    "RssNewsIngestProvider",
    "WeatherOpenMeteoIngestProvider",
    "WikipediaPageviewsIngestProvider",
]
