# intent: the single declarative catalog of MANAGED data sources — the discovery + dispatch surface behind
# `manage-data fetch/backfill/verify`; inputs: the `Providers` set + the canonical metric→provider map in
# altdata; outputs: (1) the list of expected (provider, symbol, metric) series a coverage report should find,
# (2) a per-source FETCH closure so one source can be pulled by name, (3) the BACKFILL wiring for the
# paginated sources (funding history, multi-venue bars). Invariants: this NEVER re-implements an ingest
# primitive — every fetch composes the existing `ingest_*` helpers; the alt-metric set is kept in lock-step
# with `altdata._STORE_PROVIDER_OF` (a consistency test fails if a source is added to ingest but not here).

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cosmu.data.altdata import _STORE_MARKET_WIDE, _STORE_PROVIDER_OF
from cosmu.ingest.pipeline import (
    MemoizingProvider,
    ingest_liquidations,
    ingest_market_wide_numeric,
    ingest_news_event_score,
    ingest_news_sentiment,
    ingest_numeric,
)

# Default market-bar coverage targets. Binance + Kraken via ccxt (the two venues the unified fetch layer
# manages); daily bars are the backtest's spine timeframe.
DEFAULT_BAR_VENUES = ("binance", "kraken")
DEFAULT_BAR_TIMEFRAME = "1d"
# The managed timeframes — multiple resolutions so a strategy can be screened at its native bar size (the daily
# spine + an intraday 4h/1h read). `verify` reports every (venue, symbol, timeframe) and `backfill bars` walks
# them all when no single `--timeframe` is given. Ordered coarse→fine (1d is the spine).
DEFAULT_BAR_TIMEFRAMES = ("1d", "4h", "1h")

# FRED native series id → the SEMANTIC metric it is stored under (mirrors run_once exactly). macro_regime's
# native id is operator-configurable (Providers.fred_series); the rest are fixed.
_FRED_FIXED: dict[str, str] = {
    "vix_level": "VIXCLS",
    "fed_funds_rate": "DFF",
    "dxy": "DTWEXBGS",
    "yield_curve_2s10s": "T10Y2Y",
    "credit_spread": "BAMLH0A0HYM2",
    # vix_term_slope intentionally absent: it was VIXCLS again (a phantom duplicate of vix_level), so it is no
    # longer FETCHED. It stays a DORMANT routed metric (see _DORMANT_METRICS) so banked rows remain readable.
}


@dataclass(frozen=True)
class SourceSpec:
    """One managed source. `metrics` are the SEMANTIC names it writes (the keys the coverage report and the
    store routing use). `fetch` pulls the source ONCE for the given symbols and returns the appended count;
    `backfill` (when present) walks paginated history for `days` back. `kind` is "alt" or "bars".

    `key_gated`  — True if the source requires an API key (empty [] offline; never an abort).
    `non_causal` — True if the series has no plausible causal relationship with prices (e.g. astro, weather,
                   earthquake counts). The Gate should kill these; they are included as orthogonality controls."""

    name: str
    kind: str  # "alt" | "bars"
    metrics: tuple[str, ...]
    fetch: Callable[[Any, list[str], Any], int]  # (store, symbols, providers) -> appended count
    backfill: Callable[..., dict[str, Any]] | None = None
    market_wide: bool = False
    per_symbol: bool = True
    key_gated: bool = False   # requires an API key; degrades to [] without it
    non_causal: bool = False  # no plausible causal path to price (orthogonality control)
    note: str = ""


# --------------------------------------------------------------------------- fetch closures (compose only)


def _fetch_numeric(metric: str, provider_field: str, provider_name: str) -> Callable[[Any, list[str], Any], int]:
    def fetch(store: Any, symbols: list[str], providers: Any) -> int:
        provider = getattr(providers, provider_field)
        return ingest_numeric(store, provider, symbols, metric, provider_name=provider_name)

    return fetch


def _fetch_market_wide(source_metric: str, stored_metric: str, provider_field: str, provider_name: str) -> Callable[[Any, list[str], Any], int]:
    def fetch(store: Any, symbols: list[str], providers: Any) -> int:
        provider = getattr(providers, provider_field)
        return ingest_market_wide_numeric(
            store, provider, source_metric=source_metric, stored_metric=stored_metric, provider_name=provider_name,
        )

    return fetch


# Metrics that are DISABLED in the feature_registry (mislabeled / phantom-duplicate honesty fixes) but kept
# ROUTED in _STORE_PROVIDER_OF so already-banked rows stay readable (the mind/analysts readers + the store
# as-of join still find them). They are NO LONGER fetched (no new mislabeled rows are written), but stay in
# the catalog's metric set so the catalog↔store-routing lock-step guard holds (catalog_metric_set == routes).
#   - vix_term_slope:  ingested VIXCLS — byte-identical to vix_level, NOT a term slope (phantom duplicate).
#   - exchange_netflow: the "netflow" provider fetched the Binance perp long/short ratio, NOT on-chain netflow.
_DORMANT_METRICS: tuple[str, ...] = ("vix_term_slope", "exchange_netflow")


def _fetch_dormant(store: Any, symbols: list[str], providers: Any) -> int:
    """No-op fetch for dormant (disabled-but-banked) metrics: writes nothing, returns 0. Their banked rows
    remain readable via the store route; re-enable by wiring an honest source, not by un-no-op-ing this."""
    del store, symbols, providers
    return 0


def _fetch_fred(store: Any, symbols: list[str], providers: Any) -> int:
    """All FRED-derived macro metrics in one pass, memoized so a shared native series (T10Y2Y feeds both
    macro_regime + yield_curve_2s10s) is fetched ONCE — exactly the run_once invariant, reused here. (VIXCLS
    now feeds only vix_level; the duplicate vix_term_slope was disabled — see _DORMANT_METRICS.)"""
    fred = MemoizingProvider(providers.fred)
    total = 0
    total += ingest_market_wide_numeric(store, fred, source_metric=providers.fred_series, stored_metric="macro_regime", provider_name="fred")
    for stored, native in _FRED_FIXED.items():
        total += ingest_market_wide_numeric(store, fred, source_metric=native, stored_metric=stored, provider_name="fred")
    return total


def _fetch_news(store: Any, symbols: list[str], providers: Any) -> int:
    n = ingest_news_sentiment(store, providers.news, symbols, llm=getattr(providers, "llm", None))
    # The event scorer uses the cheap-OpenRouter formatter (key-gated → None = deterministic lexicon).
    n += ingest_news_event_score(store, providers.news, symbols, llm=getattr(providers, "event_llm", None))
    return n


def _fetch_multiasset(store: Any, symbols: list[str], providers: Any) -> int:
    """All cross-asset daily price levels (metals / commodities / equity indexes / FX) in one pass, each
    market-wide under its SEMANTIC name (free, no key). Composes ingest_market_wide_numeric — no re-impl."""
    from cosmu.data.sources.multiasset import MULTIASSET_METRICS

    total = 0
    for metric in MULTIASSET_METRICS:
        total += ingest_market_wide_numeric(
            store, providers.multiasset, source_metric=metric, stored_metric=metric, provider_name="stooq",
        )
    return total


def _fetch_polymarket_clob(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"):
        total += ingest_market_wide_numeric(
            store, providers.polymarket_clob, source_metric=metric, stored_metric=metric, provider_name="polymarket",
        )
    return total


# All twelve LunarCrush coin time-series fields the provider now maps (in lockstep with the bulk hoard,
# scripts/lunarcrush_max_extract.py _COIN_FIELDS). The provider returns one HTTP response per symbol and the
# memoizing wrapper caches it, so fetching twelve metrics is still one network call per symbol.
_LUNARCRUSH_METRICS = (
    "social_volume", "social_sentiment", "galaxy_score",
    "alt_rank", "market_cap_usd", "volume_24h_usd", "price_usd",
    "social_dominance", "market_dominance", "contributors_active", "posts_active", "spam",
)


def _fetch_lunarcrush(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in _LUNARCRUSH_METRICS:
        total += ingest_numeric(store, providers.lunarcrush, symbols, metric, provider_name="lunarcrush")
    return total


def _fetch_xai(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("twitter_sentiment", "twitter_influencer_sentiment"):
        total += ingest_market_wide_numeric(
            store, providers.xai_twitter, source_metric=metric, stored_metric=metric, provider_name="xai",
        )
    return total


def _fetch_gdelt_tone(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.gdelt_tone, source_metric="gdelt_tone", stored_metric="gdelt_tone", provider_name="gdelt",
    )


def _fetch_dvol(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_numeric(store, providers.dvol, symbols, "dvol", provider_name="deribit")


def _fetch_llm_index(store: Any, symbols: list[str], providers: Any) -> int:
    """LLM qualitative→quantitative index scores — each market-wide under its semantic name. Key-gated (no LLM
    key → provider returns [] → 0, never an abort). The LLM only proposes the rubric-anchored number at ingest."""
    from cosmu.lab.indexes import INDEX_RUBRICS

    total = 0
    for metric in INDEX_RUBRICS:
        total += ingest_market_wide_numeric(
            store, providers.llm_index, source_metric=metric, stored_metric=metric, provider_name="llm_index",
        )
    return total


def _fetch_risk_on(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.polymarket, source_metric=providers.polymarket_token, stored_metric="pm_risk_on", provider_name="polymarket",
    )


def _fetch_venue_fees(store: Any, symbols: list[str], providers: Any) -> int:
    from cosmu.ingest.run import _ingest_venue_fees

    return _ingest_venue_fees(store, providers.venue_fees, symbols)


# --------------------------------------------------------------------------- the 10 new alt sources

# Extended FRED macro (NFCI financial conditions + initial jobless claims) — each its own ALFRED
# initial-release provider so available_at == realtime_start (no look-ahead). Market-wide.
def _fetch_macro_extra(store: Any, symbols: list[str], providers: Any) -> int:
    from cosmu.data.providers.macro_extra import METRIC_INITIAL_CLAIMS, METRIC_NFCI

    total = 0
    total += ingest_market_wide_numeric(
        store, providers.nfci, source_metric=METRIC_NFCI, stored_metric="nfci", provider_name="fred",
    )
    total += ingest_market_wide_numeric(
        store, providers.initial_claims, source_metric=METRIC_INITIAL_CLAIMS, stored_metric="initial_claims", provider_name="fred",
    )
    return total


# Wikipedia pageviews — per-symbol (raw + log + 30d z-score), one bridge provider per derived metric.
_WIKI_METRICS = ("wiki_pageviews", "wiki_pageviews_log", "wiki_pageviews_zscore")


def _fetch_wikipedia(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in _WIKI_METRICS:
        total += ingest_numeric(store, providers.wiki_pageviews, symbols, metric, provider_name="wikimedia")
    return total


# Reddit daily post + comment volume — market-wide attention proxy (key-gated → [] offline).
def _fetch_reddit_volume(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("reddit_post_volume", "reddit_comment_volume"):
        total += ingest_market_wide_numeric(
            store, providers.reddit_volume, source_metric=metric, stored_metric=metric, provider_name="reddit_volume",
        )
    return total


# CryptoPanic news votes — per-symbol bullish/bearish (key-gated → [] offline).
def _fetch_cryptopanic(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("cryptopanic_bullish_votes", "cryptopanic_bearish_votes"):
        total += ingest_numeric(store, providers.cryptopanic, symbols, metric, provider_name="cryptopanic")
    return total


def _fetch_rss_news(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.rss_news, source_metric="rss_news_count", stored_metric="rss_news_count", provider_name="rss",
    )


def _fetch_gtrends(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.gtrends, source_metric="gtrends_search_interest", stored_metric="gtrends_search_interest", provider_name="gtrends",
    )


def _fetch_opensky_daily(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.opensky_daily, source_metric="opensky_daily_flights", stored_metric="opensky_daily_flights", provider_name="opensky_daily",
    )


def _fetch_weather(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.weather, source_metric="weather_hub_stress", stored_metric="weather_hub_stress", provider_name="openmeteo",
    )


# Deterministic astro ephemeris — source-native metric → semantic feature name. NON-CAUSAL controls.
_ASTRO_METRIC_MAP = {
    "lunar_phase_fraction": "astro_lunar_phase",
    "sun_longitude_deg": "astro_sun_longitude",
    "jupiter_longitude_deg": "astro_jupiter_longitude",
    "saturn_longitude_deg": "astro_saturn_longitude",
    "sun_jupiter_aspect": "astro_sun_jupiter_aspect",
}


def _fetch_astro(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for native, stored in _ASTRO_METRIC_MAP.items():
        total += ingest_market_wide_numeric(
            store, providers.astro, source_metric=native, stored_metric=stored, provider_name="astro",
        )
    return total


# Exotic orthogonality controls — split across two store providers (USGS earthquakes, NOAA Kp).
def _fetch_exotic_controls(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("usgs_earthquake_count", "usgs_max_magnitude"):
        total += ingest_market_wide_numeric(
            store, providers.exotic_controls, source_metric=metric, stored_metric=metric, provider_name="usgs",
        )
    total += ingest_market_wide_numeric(
        store, providers.exotic_controls, source_metric="noaa_kp_index", stored_metric="noaa_kp_index", provider_name="noaa",
    )
    return total


# --------------------------------------------------------------------------- TOOL-WAVE-A: 4 more free sources

# DefiLlama total stablecoin market cap — market-wide (free, no key). The legacy defi_tvl is its own source
# above; this only ADDS the orthogonal stablecoin_mcap metric under the same "defillama" store bucket.
def _fetch_defillama_stablecoin(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_market_wide_numeric(
        store, providers.defillama_stablecoin, source_metric="stablecoin_mcap", stored_metric="stablecoin_mcap", provider_name="defillama",
    )


# CoinGecko (free public tier) — per-coin mcap + 24h volume (per-symbol), plus market-wide BTC dominance.
def _fetch_coingecko(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in ("cg_market_cap", "cg_total_volume"):
        total += ingest_numeric(store, providers.coingecko, symbols, metric, provider_name="coingecko")
    total += ingest_market_wide_numeric(
        store, providers.coingecko, source_metric="cg_btc_dominance", stored_metric="cg_btc_dominance", provider_name="coingecko",
    )
    return total


# blockchain.com BTC on-chain fundamentals — all market-wide (describe the whole BTC network), free, no key.
_ONCHAIN_METRICS = ("btc_hashrate", "btc_tx_count", "btc_mempool_size", "btc_active_addresses")


def _fetch_onchain_blockchain(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in _ONCHAIN_METRICS:
        total += ingest_market_wide_numeric(
            store, providers.onchain_blockchain, source_metric=metric, stored_metric=metric, provider_name="blockchain.com",
        )
    return total


# GDELT daily news-VOLUME counts — per-symbol (the topic query is resolved from the symbol), free, no key.
def _fetch_gdelt_counts(store: Any, symbols: list[str], providers: Any) -> int:
    return ingest_numeric(store, providers.gdelt_counts, symbols, "gdelt_news_volume", provider_name="gdelt_counts")


# --------------------------------------------------------------------------- TOOL-WAVE-C: 2 more free sources

# FRED keyless macro-liquidity (Fed balance sheet + net-of-TGA) — both market-wide, free, no key. Stored under
# the SAME "fred" provider bucket as the other macro metrics; distinct semantic metrics, knowable ~T+8.
_ETF_FLOW_METRICS = ("fed_balance_sheet_usd", "net_liquidity_usd")


def _fetch_etf_flows(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in _ETF_FLOW_METRICS:
        total += ingest_market_wide_numeric(
            store, providers.etf_flows, source_metric=metric, stored_metric=metric, provider_name="fred",
        )
    return total


# DefiLlama stablecoin FLOW (day-over-day mcap CHANGE) + ETH chain-share — both market-wide, free, no key.
# Stored under the SAME "defillama" provider bucket as defi_tvl / stablecoin_mcap; orthogonal flow metrics.
_STABLECOIN_FLOW_METRICS = ("stablecoin_net_flow_usd", "stablecoin_eth_share")


def _fetch_stablecoin_flows(store: Any, symbols: list[str], providers: Any) -> int:
    total = 0
    for metric in _STABLECOIN_FLOW_METRICS:
        total += ingest_market_wide_numeric(
            store, providers.stablecoin_flows, source_metric=metric, stored_metric=metric, provider_name="defillama",
        )
    return total


# --------------------------------------------------------------------------- historical backfill closures
# These give the CURRENT-ONLY adapters real date-range depth: each source's `backfill(days=N)` pulls a
# paginated history window (one request per series — the archive APIs serve a [start,end] range natively),
# returns PIT-stamped AltDataPoints, and is written append-only + deduped on (provider,symbol,metric,ts) so a
# re-run writes 0.  All remain offline-deterministic (the underlying sources degrade to fixtures). The bridge
# closures compose `append_dedup` — they never re-implement a fetch primitive.


def _provider_offline(provider: Any) -> bool:
    """Duck-typed: honour an `offline` flag on the bridge provider so a manage test stays network-free."""
    return bool(getattr(provider, "offline", False))


def _backfill_weather(store: Any, symbols: list[str], providers: Any, *, days: int, as_of: Any = None) -> dict[str, Any]:
    """Open-Meteo financial-hub weather stress: market-wide daily history via the archive date-range API."""
    from cosmu.data.sources.weather_openmeteo import WeatherOpenMeteoSource
    from cosmu.ingest.pipeline import append_dedup

    del symbols  # market-wide
    provider = getattr(providers, "weather", None)
    offline = _provider_offline(provider)
    # A bridge provider may carry a wide `backfill_fixture` seam (offline-with-depth tests). DRY: reuse it.
    fixture = getattr(provider, "backfill_fixture", None)
    src = (
        WeatherOpenMeteoSource(offline=offline, _fixture=fixture)
        if fixture is not None
        else WeatherOpenMeteoSource(offline=offline)
    )
    pts = src.backfill(days, as_of=as_of)
    written = append_dedup(store, "openmeteo", "MARKET", "weather_hub_stress", pts)
    return {"weather_hub_stress": {"written": written, "total": len(pts)}}


def _backfill_wikipedia(store: Any, symbols: list[str], providers: Any, *, days: int, as_of: Any = None) -> dict[str, Any]:
    """Wikipedia pageviews: per-symbol raw + log + 30d-zscore daily history via the REST date-range API."""
    from cosmu.data.sources.wikipedia_pageviews import WikipediaPageviewsSource
    from cosmu.ingest.pipeline import append_dedup

    # Honour a `_fetcher` injected on the bridge provider so a manage test can drive this offline.
    fetcher = getattr(getattr(providers, "wiki_pageviews", None), "_fetcher", None)
    out: dict[str, Any] = {}
    for metric in _WIKI_METRICS:
        src = WikipediaPageviewsSource(metric=metric, _fetcher=fetcher) if fetcher else WikipediaPageviewsSource(metric=metric)
        written = total = 0
        for symbol in symbols:
            pts = src.backfill(symbol, days, as_of=as_of)
            written += append_dedup(store, "wikimedia", symbol, metric, pts)
            total += len(pts)
        out[metric] = {"written": written, "total": total}
    return out


def _backfill_coingecko(store: Any, symbols: list[str], providers: Any, *, days: int, as_of: Any = None) -> dict[str, Any]:
    """CoinGecko daily history: per-coin market cap + 24h volume via market_chart's date-range (one request
    per coin), plus the market-wide BTC dominance snapshot. Mirrors _backfill_wikipedia (per-symbol raw
    series, source's own as_of clock, idempotent append-dedup on (provider,symbol,metric,ts))."""
    from datetime import UTC, datetime

    from cosmu.data.sources.coingecko import CoinGeckoSource
    from cosmu.ingest.pipeline import append_dedup

    # Honour a `_fetcher` injected on the bridge provider so a manage test can drive this offline.
    fetcher = getattr(getattr(providers, "coingecko", None), "_fetcher", None)
    now = as_of or datetime.now(tz=UTC)
    out: dict[str, Any] = {}
    # Per-coin daily series: lookback_days = the requested depth so market_chart returns the full window.
    for metric in ("cg_market_cap", "cg_total_volume"):
        src = CoinGeckoSource(metric=metric, lookback_days=days, _fetcher=fetcher) if fetcher else CoinGeckoSource(metric=metric, lookback_days=days)
        written = total = 0
        for symbol in symbols:
            pts = src.fetch_raw_series(symbol, now)
            written += append_dedup(store, "coingecko", symbol, metric, pts)
            total += len(pts)
        out[metric] = {"written": written, "total": total}
    # Market-wide BTC dominance: a current snapshot from /global (no deep history) — one MARKET point.
    src = CoinGeckoSource(metric="cg_btc_dominance", _fetcher=fetcher) if fetcher else CoinGeckoSource(metric="cg_btc_dominance")
    pts = src.fetch_raw_series("MARKET", now)
    written = append_dedup(store, "coingecko", "MARKET", "cg_btc_dominance", pts)
    out["cg_btc_dominance"] = {"written": written, "total": len(pts)}
    return out


def _backfill_gdelt_counts(store: Any, symbols: list[str], providers: Any, *, days: int, as_of: Any = None) -> dict[str, Any]:
    """GDELT daily news-volume history: per-symbol counts via the DOC 2.0 timeline date-range (one request
    per symbol). Mirrors _backfill_wikipedia (per-symbol raw series, source's own as_of clock, idempotent
    append-dedup on (provider,symbol,metric,ts))."""
    from datetime import UTC, datetime

    from cosmu.data.sources.gdelt_counts import GdeltCountsSource
    from cosmu.ingest.pipeline import append_dedup

    fetcher = getattr(getattr(providers, "gdelt_counts", None), "_fetcher", None)
    now = as_of or datetime.now(tz=UTC)
    src = GdeltCountsSource(lookback_days=days, _fetcher=fetcher) if fetcher else GdeltCountsSource(lookback_days=days)
    written = total = 0
    for symbol in symbols:
        pts = src.fetch_raw_series(symbol, now)
        written += append_dedup(store, "gdelt_counts", symbol, "gdelt_news_volume", pts)
        total += len(pts)
    return {"gdelt_news_volume": {"written": written, "total": total}}


def _backfill_exotic_controls(store: Any, symbols: list[str], providers: Any, *, days: int, as_of: Any = None) -> dict[str, Any]:
    """USGS earthquakes (count + max-mag via FDSN query) + NOAA Kp (3-hourly→daily-max) market-wide history."""
    from cosmu.data.sources.exotic_controls import (
        NoaaKpIndexSource,
        UsgsEarthquakeSource,
        UsgsMaxMagnitudeSource,
    )
    from cosmu.ingest.pipeline import append_dedup

    del symbols
    provider = getattr(providers, "exotic_controls", None)
    offline = _provider_offline(provider)
    # Optional injected history fetchers (offline-with-depth tests): provider may carry
    # `usgs_history_fetcher` (FDSN query JSON) and `kp_history_fetcher` (NOAA 3-hourly rows).
    usgs_fetcher = getattr(provider, "usgs_history_fetcher", None)
    kp_fetcher = getattr(provider, "kp_history_fetcher", None)
    out: dict[str, Any] = {}
    for metric, src, store_provider in (
        ("usgs_earthquake_count", UsgsEarthquakeSource(offline=offline, _history_fetcher=usgs_fetcher), "usgs"),
        ("usgs_max_magnitude", UsgsMaxMagnitudeSource(offline=offline, _history_fetcher=usgs_fetcher), "usgs"),
        ("noaa_kp_index", NoaaKpIndexSource(offline=offline, _history_fetcher=kp_fetcher), "noaa"),
    ):
        pts = src.backfill(days, as_of=as_of)
        written = append_dedup(store, store_provider, "MARKET", metric, pts)
        out[metric] = {"written": written, "total": len(pts)}
    return out


# --------------------------------------------------------------------------- the catalog


def managed_sources() -> dict[str, SourceSpec]:
    """The catalog, built fresh each call (no global mutable state). Keyed by the friendly source name the
    CLI accepts (`manage-data fetch funding`). Bars are handled by the manager's backfill path, not here."""
    specs: list[SourceSpec] = [
        SourceSpec("funding", "alt", ("funding_rate",), _fetch_numeric("funding_rate", "funding", "binance"), note="Binance USDⓈ-M funding (paginated history)."),
        SourceSpec("fear_greed", "alt", ("fear_greed",), _fetch_market_wide("fear_greed", "fear_greed", "feargreed", "alternative.me"), market_wide=True, per_symbol=False),
        SourceSpec("news", "alt", ("news_sentiment", "news_event_score"), _fetch_news, note="GDELT headlines → standardized sentiment + typed event score (LLM only at ingest)."),
        SourceSpec("macro", "alt", ("macro_regime", "vix_level", "fed_funds_rate", "dxy", "yield_curve_2s10s", "credit_spread"), _fetch_fred, market_wide=True, per_symbol=False, note="FRED macro bundle (memoized shared series)."),
        SourceSpec("defi", "alt", ("defi_tvl",), _fetch_market_wide("defi_tvl", "defi_tvl", "defillama", "defillama"), market_wide=True, per_symbol=False),
        SourceSpec("pm_risk_on", "alt", ("pm_risk_on",), _fetch_risk_on, market_wide=True, per_symbol=False),
        SourceSpec("liquidation_cascade", "alt", ("liquidation_cascade",), lambda store, symbols, providers: ingest_liquidations(store, providers.liquidations, symbols)),
        SourceSpec("putcall", "alt", ("putcall_ratio",), _fetch_market_wide("putcall_ratio", "putcall_ratio", "putcall", "cboe"), market_wide=True, per_symbol=False),
        SourceSpec("open_interest", "alt", ("open_interest",), _fetch_numeric("open_interest", "open_interest", "binance")),
        SourceSpec("basis", "alt", ("perp_spot_basis",), _fetch_numeric("perp_spot_basis", "basis", "binance")),
        SourceSpec("osint", "alt", ("osint_air_activity",), _fetch_market_wide("osint_air_activity", "osint_air_activity", "osint", "opensky"), market_wide=True, per_symbol=False),
        SourceSpec("polymarket_clob", "alt", ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"), _fetch_polymarket_clob, market_wide=True, per_symbol=False),
        SourceSpec("reddit", "alt", ("reddit_sentiment",), _fetch_market_wide("reddit_sentiment", "reddit_sentiment", "reddit", "reddit"), market_wide=True, per_symbol=False),
        SourceSpec("lunarcrush", "alt", _LUNARCRUSH_METRICS, _fetch_lunarcrush, key_gated=True, note="Key-gated: empty without LUNARCRUSH_API_KEY."),
        SourceSpec("xai", "alt", ("twitter_sentiment", "twitter_influencer_sentiment"), _fetch_xai, market_wide=True, per_symbol=False, key_gated=True, note="Key-gated: empty without XAI_API_KEY."),
        SourceSpec("venue_fees", "alt", ("venue_fees_maker", "venue_fees_taker"), _fetch_venue_fees, note="Per venue:symbol maker/taker snapshot."),
        SourceSpec(
            "multiasset", "alt",
            ("gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy"),
            _fetch_multiasset, market_wide=True, per_symbol=False,
            note="Free cross-asset daily price levels via Stooq/Yahoo (metals/commodities/equity-index/FX).",
        ),
        SourceSpec("gdelt_tone", "alt", ("gdelt_tone",), _fetch_gdelt_tone, market_wide=True, per_symbol=False, note="GDELT geopolitical news tone (keyless, EU-accessible, market-wide daily)."),
        SourceSpec("dvol", "alt", ("dvol",), _fetch_dvol, note="Deribit DVOL implied vol (keyless, EU-native, BTC/ETH only)."),
        SourceSpec("llm_index", "alt", tuple(_index_metrics()), _fetch_llm_index, market_wide=True, per_symbol=False, key_gated=True, note="LLM qualitative→quantitative index scores (key-gated; market-wide)."),
        # --- 10 new alt-data sources (registered additively; non-causal ones flagged in feature_registry) ---
        SourceSpec("macro_extra", "alt", ("nfci", "initial_claims"), _fetch_macro_extra, market_wide=True, per_symbol=False, note="Extended FRED macro: NFCI financial conditions + initial jobless claims (ALFRED initial-release vintages)."),
        SourceSpec("wikipedia", "alt", _WIKI_METRICS, _fetch_wikipedia, backfill=_backfill_wikipedia, note="Wikipedia pageviews per entity (raw + log + 30d z-score); free, no key, immutable counts (T+1). Paginated date-range backfill."),
        SourceSpec("reddit_volume", "alt", ("reddit_post_volume", "reddit_comment_volume"), _fetch_reddit_volume, market_wide=True, per_symbol=False, key_gated=True, note="Reddit daily post + comment volume (key-gated: REDDIT_CLIENT_ID/SECRET → empty offline)."),
        SourceSpec("cryptopanic", "alt", ("cryptopanic_bullish_votes", "cryptopanic_bearish_votes"), _fetch_cryptopanic, key_gated=True, note="CryptoPanic per-coin bullish/bearish vote counts, 24h window (key-gated: CRYPTOPANIC_API_KEY → empty offline)."),
        SourceSpec("rss", "alt", ("rss_news_count",), _fetch_rss_news, market_wide=True, per_symbol=False, note="Public RSS headline COUNT (LLM-free, free, no key)."),
        SourceSpec("gtrends", "alt", ("gtrends_search_interest",), _fetch_gtrends, market_wide=True, per_symbol=False, note="Google Trends search interest (REVISION HAZARD: rescales history — paper only until Gate-validated)."),
        SourceSpec("opensky_daily", "alt", ("opensky_daily_flights",), _fetch_opensky_daily, market_wide=True, per_symbol=False, note="OpenSky daily global flight count (free OSINT, thin history, low-confidence)."),
        SourceSpec("weather", "alt", ("weather_hub_stress",), _fetch_weather, backfill=_backfill_weather, market_wide=True, per_symbol=False, non_causal=True, note="Open-Meteo financial-hub weather stress (NON-CAUSAL control; free, no key). Paginated archive date-range backfill."),
        SourceSpec("astro", "alt", tuple(_ASTRO_METRIC_MAP.values()), _fetch_astro, market_wide=True, per_symbol=False, non_causal=True, note="Deterministic lunar/planetary ephemeris (NON-CAUSAL controls; stdlib-only, no network)."),
        SourceSpec("exotic_controls", "alt", ("usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index"), _fetch_exotic_controls, backfill=_backfill_exotic_controls, market_wide=True, per_symbol=False, non_causal=True, note="USGS earthquakes + NOAA Kp ORTHOGONALITY CONTROLS (non-causal; Gate must kill them). Paginated date-range backfill (FDSN query + NOAA 3-hourly history)."),
        # --- TOOL-WAVE-A: 4 more free, no-key sources (PIT-honest; daily aggregates knowable T+1; degrade to [] offline) ---
        SourceSpec("defillama_stablecoin", "alt", ("stablecoin_mcap",), _fetch_defillama_stablecoin, market_wide=True, per_symbol=False, note="DefiLlama total circulating stablecoin market cap (free, no key, market-wide). Orthogonal to the legacy defi_tvl."),
        SourceSpec("coingecko", "alt", ("cg_market_cap", "cg_total_volume", "cg_btc_dominance"), _fetch_coingecko, backfill=_backfill_coingecko, note="CoinGecko free public tier: per-coin market cap + 24h volume, plus market-wide BTC dominance (no key). Paginated market_chart date-range backfill for the per-coin series."),
        SourceSpec("onchain_blockchain", "alt", _ONCHAIN_METRICS, _fetch_onchain_blockchain, market_wide=True, per_symbol=False, note="blockchain.com BTC on-chain fundamentals: hashrate, tx count, mempool size, active addresses (free, no key, market-wide)."),
        SourceSpec("gdelt_counts", "alt", ("gdelt_news_volume",), _fetch_gdelt_counts, backfill=_backfill_gdelt_counts, note="GDELT 2.0 daily per-topic news-VOLUME COUNT (free, no key, LLM-free; per-symbol). Distinct from gdelt_tone. Paginated DOC 2.0 timeline date-range backfill."),
        # --- TOOL-WAVE-C: 2 more free, no-key market-wide FLOW sources (PIT-honest; degrade to [] offline) ---
        SourceSpec("etf_flows", "alt", _ETF_FLOW_METRICS, _fetch_etf_flows, market_wide=True, per_symbol=False, note="FRED keyless macro-liquidity: Fed balance sheet (WALCL) + net liquidity (WALCL - TGA); free, no key, market-wide, knowable ~T+8."),
        SourceSpec("stablecoin_flows", "alt", _STABLECOIN_FLOW_METRICS, _fetch_stablecoin_flows, market_wide=True, per_symbol=False, note="DefiLlama stablecoin FLOW: day-over-day net mint/redeem + Ethereum chain-share; free, no key, market-wide, knowable T+1. Orthogonal to the level series stablecoin_mcap."),
        # DORMANT (no-op fetch): disabled-but-banked metrics kept ROUTED so old rows stay readable and the
        # catalog↔store-routing lock-step holds, but NEVER re-ingested (mislabeled / phantom-duplicate honesty
        # fixes — see _DORMANT_METRICS). per_symbol=False so coverage uses the canonical store route, not a fan-out.
        SourceSpec("dormant", "alt", _DORMANT_METRICS, _fetch_dormant, per_symbol=False, note="Disabled-but-banked metrics (vix_term_slope, exchange_netflow): routed for readability, never re-ingested."),
    ]
    return {s.name: s for s in specs}


def _index_metrics() -> tuple[str, ...]:
    """The LLM index metric names, derived from the rubric registry (DRY — never a second hand-listing)."""
    from cosmu.lab.indexes import INDEX_RUBRICS

    return tuple(INDEX_RUBRICS)


def source_names() -> list[str]:
    return sorted(managed_sources())


def expected_alt_specs(symbols: list[str], *, venue: str = "binance") -> list[tuple[str, str, str]]:
    """Every (store_provider, store_symbol, metric) the coverage report should find, derived from the
    CANONICAL `_STORE_PROVIDER_OF` map (not a re-listing). Market-wide metrics live under the MARKET key;
    venue-fee metrics live under a `<venue>:<symbol>` composite key; everything else is per-symbol."""
    out: list[tuple[str, str, str]] = []
    for metric, provider in sorted(_STORE_PROVIDER_OF.items()):
        if metric in ("venue_fees_maker", "venue_fees_taker"):
            for sym in symbols:
                out.append((provider, f"{venue}:{sym}", metric))
        elif metric in _STORE_MARKET_WIDE:
            out.append((provider, "MARKET", metric))
        else:
            for sym in symbols:
                out.append((provider, sym, metric))
    return out


def expected_bar_specs(
    symbols: list[str],
    *,
    venues: tuple[str, ...] = DEFAULT_BAR_VENUES,
    timeframes: tuple[str, ...] = DEFAULT_BAR_TIMEFRAMES,
) -> list[tuple[str, str, str]]:
    """Every (venue, symbol, timeframe) bar series the report should find in the on-disk cache — now across
    MULTIPLE timeframes (the daily spine + intraday reads), so `verify` names a missing 4h/1h cache the same
    way it names a missing source."""
    return [(venue, sym, tf) for venue in venues for sym in symbols for tf in timeframes]


def catalog_metric_set() -> set[str]:
    """Union of every semantic metric the catalog's sources write — used by the consistency test to prove the
    catalog stays in lock-step with `_STORE_PROVIDER_OF`."""
    metrics: set[str] = set()
    for spec in managed_sources().values():
        metrics.update(spec.metrics)
    return metrics
