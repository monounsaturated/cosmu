# intent: the one-pass, cron-able free-data ingest CLI — arrange the free sources once, hit go, fill the append-only point-in-time alt-data store; inputs: the real free providers (funding/F&G/GDELT news/FRED macro/Polymarket odds/Coinglass liquidations/CBOE put-call), injectable so tests run offline on fixtures; outputs: per-source append counts into the store the cross-asset gate reads; invariants: append-only + point-in-time (re-runs never rewrite the view), ZERO API keys required, ONE pass per invocation (NOT a daemon), per-source failure is caught and logged as a 0 count so one dead source never aborts the pass, and the LLM runs ONLY at news standardization (cached, offline lexicon by default).

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from cosmu.config.settings import get_settings
from cosmu.data.altdata import (
    AltDataPoint,
    AltDataProvider,
    AltDataStore,
    BinanceBasisProvider,
    BinanceOpenInterestProvider,
    CboePutCallProvider,
    CoinglassLiquidationProvider,
    DefiLlamaTvlProvider,
    DeribitDvolProvider,
    ExchangeNetflowProvider,
    FearGreedProvider,
    FredMacroProvider,
    FundingRateProvider,
    GdeltNewsProvider,
    GdeltToneProvider,
    KrakenFuturesFundingRateProvider,
    LunarCrushProvider,
    NewsProvider,
    OkxFundingRateProvider,
    OsintAirActivityProvider,
    PolymarketClobProvider,
    PolymarketGammaProvider,
    PolymarketOddsProvider,
    RedditSentimentProvider,
    VenueFeesProvider,
)
from cosmu.data.sources.multiasset import MULTIASSET_METRICS, StooqDailyProvider
from cosmu.data.sources.xai_twitter import XaiTwitterProvider
from cosmu.ingest.llm_formatter import build_event_formatter_from_settings
from cosmu.ingest.pipeline import (
    MemoizingProvider,
    ingest_liquidations,
    ingest_market_wide_numeric,
    ingest_news_event_score,
    ingest_news_sentiment,
    ingest_numeric,
    ingest_putcall,
)
from cosmu.ingest.standardize import NewsEventScore, StandardizedNews
from cosmu.lab.indexes import (
    INDEX_RUBRICS,
    LlmIndexProvider,
    NewsEvidenceProvider,
    build_index_provider_from_settings,
)

logger = logging.getLogger("cosmu.ingest.run")

# Default crypto universe (mirrors the seeded Binance instruments in spine.venue.default_catalog).
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
# Native source ids for the two market-wide cross-asset transfer series — mapped to their SEMANTIC
# names (macro_regime / risk_on) at ingest, exactly as ingest_cross_asset_sources does.
DEFAULT_FRED_SERIES = "T10Y2Y"  # 10y-2y curve slope: one macro read conditions risk across classes
DEFAULT_POLYMARKET_TOKEN = "risk-on"  # a market token id; real runs override via --polymarket-token

# 20-asset OKX USDT-M perpetual-swap universe for the funding-dispersion strategy.
# Symbols match the OKX public API `instId` format (<BASE>-USDT-SWAP).
OKX_PERP_UNIVERSE = (
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "XRP-USDT-SWAP",
    "LINK-USDT-SWAP", "AVAX-USDT-SWAP", "ADA-USDT-SWAP", "DOT-USDT-SWAP",
    "POL-USDT-SWAP", "ATOM-USDT-SWAP", "LTC-USDT-SWAP", "BCH-USDT-SWAP",
    "DOGE-USDT-SWAP", "NEAR-USDT-SWAP", "UNI-USDT-SWAP", "FIL-USDT-SWAP",
    "INJ-USDT-SWAP", "OP-USDT-SWAP", "ARB-USDT-SWAP", "TON-USDT-SWAP",
)

# Kraken Futures linear perpetuals available for data ingest (PF_ = linear USDT-settled).
# Smaller universe than OKX; funding settled hourly via premium index.
KRAKEN_FUTURES_UNIVERSE = (
    "PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD", "PF_XRPUSD", "PF_LINKUSD",
    "PF_AVAXUSD", "PF_ADAUSD", "PF_DOTUSD", "PF_DOGEUSD", "PF_LTCUSD",
)


@dataclass
class Providers:
    """The injectable set of free providers. Default = the REAL free APIs (zero keys). Tests pass fixtures
    so a pass runs fully offline. News standardization uses the offline lexicon unless an `llm` is given."""

    funding: AltDataProvider = field(default_factory=FundingRateProvider)
    # OKX perp funding rate for the 20-asset dispersion universe (public endpoint, no key).
    okx_funding: AltDataProvider = field(default_factory=OkxFundingRateProvider)
    # Kraken Futures funding rate (public endpoint, no key). FR-legal perp venue (MiCA EU).
    kraken_futures_funding: AltDataProvider = field(default_factory=KrakenFuturesFundingRateProvider)
    feargreed: AltDataProvider = field(default_factory=FearGreedProvider)
    news: NewsProvider = field(default_factory=GdeltNewsProvider)
    fred: AltDataProvider = field(default_factory=FredMacroProvider)
    polymarket: AltDataProvider = field(default_factory=lambda: PolymarketGammaProvider())
    liquidations: AltDataProvider = field(default_factory=CoinglassLiquidationProvider)
    putcall: AltDataProvider = field(default_factory=CboePutCallProvider)
    defillama: AltDataProvider = field(default_factory=DefiLlamaTvlProvider)
    open_interest: AltDataProvider = field(default_factory=BinanceOpenInterestProvider)
    basis: AltDataProvider = field(default_factory=BinanceBasisProvider)
    netflow: AltDataProvider = field(default_factory=ExchangeNetflowProvider)
    osint: AltDataProvider = field(default_factory=OsintAirActivityProvider)
    polymarket_clob: AltDataProvider = field(default_factory=lambda: PolymarketClobProvider())
    # Social feeds: Reddit is free (no key); LunarCrush is key-gated → empty without LUNARCRUSH_API_KEY.
    reddit: AltDataProvider = field(default_factory=RedditSentimentProvider)
    lunarcrush: AltDataProvider = field(default_factory=lambda: LunarCrushProvider())
    # xAI/Grok Twitter sentiment: key-gated — returns [] without XAI_API_KEY (honest degradation).
    # LLM only standardizes text; never touches the gate/scoring/money path.
    xai_twitter: AltDataProvider = field(default_factory=lambda: XaiTwitterProvider())
    # LLM qualitative→quantitative index scores (reg_risk_crypto / risk_on_off). Key-gated: no LLM key → the
    # provider ingests nothing (honest). The LLM only proposes the rubric-anchored number; the Gate disposes.
    llm_index: AltDataProvider = field(
        default_factory=lambda: LlmIndexProvider(evidence=NewsEvidenceProvider(GdeltNewsProvider()))
    )
    # Venue fees: key-gated (ccxt exchange needed for live reads). Default = Binance static-catalog fallback
    # (offline-safe, no key). A live ccxt client can be injected at deploy time for account-specific rates.
    venue_fees: AltDataProvider = field(default_factory=lambda: VenueFeesProvider("binance"))
    # Cross-asset daily price levels (free, no key): Stooq is primary; YahooDailyProvider is a drop-in alt.
    multiasset: AltDataProvider = field(default_factory=StooqDailyProvider)
    # EU-accessible, keyless: GDELT geopolitical news tone (market-wide) + Deribit DVOL (per-symbol BTC/ETH).
    gdelt_tone: AltDataProvider = field(default_factory=GdeltToneProvider)
    dvol: AltDataProvider = field(default_factory=DeribitDvolProvider)
    llm: Callable[[str], StandardizedNews] | None = None
    # Typed event/news scorer LLM (the cheap-OpenRouter formatter). Key-gated → None without a key, so the
    # event scorer uses the deterministic lexicon. The LLM only standardizes text at ingest, never the money path.
    event_llm: Callable[[str], NewsEventScore] | None = None
    fred_series: str = DEFAULT_FRED_SERIES
    polymarket_token: str = DEFAULT_POLYMARKET_TOKEN

    @classmethod
    def from_settings(cls, settings) -> "Providers":  # noqa: ANN001
        """Build the real free providers WITH the operator's keys/tokens wired in — so setting FRED_API_KEY
        (free) and POLYMARKET_TOKEN (a real market id) is all it takes for macro_regime / risk_on to connect.
        Sources needing nothing (Binance/Fear&Greed/GDELT) work regardless; missing key/token → that one
        source stays empty (caught by _safe), never crashing the pass."""
        pin = settings.polymarket_token or None
        return cls(
            fred=FredMacroProvider(api_key=settings.fred_api_key),
            polymarket=PolymarketGammaProvider(pin_token=pin),
            polymarket_clob=PolymarketClobProvider(pin_token=pin),
            # LunarCrush only connects when LUNARCRUSH_API_KEY is set; no key → the provider returns [] (honest).
            lunarcrush=LunarCrushProvider(api_key=settings.lunarcrush_api_key or ""),
            # xAI/Grok Twitter: key-gated — only live when XAI_API_KEY is set in Railway env.
            xai_twitter=XaiTwitterProvider(api_key=settings.xai_api_key or ""),
            # Typed event/news scorer via the cheap-OpenRouter formatter — key-gated (None without OPENROUTER_API_KEY).
            event_llm=build_event_formatter_from_settings(settings),
            # LLM index scorer — xAI preferred, OpenRouter fallback; no key → ingests nothing (honest).
            llm_index=build_index_provider_from_settings(settings),
            polymarket_token="risk_on",
        )


def _default_store():  # noqa: ANN202 - AltDataStore | PgAltDataStore
    """Pick the backend the SAME way the API does: postgres URL → PgAltDataStore over the Store, else the
    JSONL AltDataStore. ZERO keys required — both are append-only point-in-time stores with one interface."""
    settings = get_settings()
    if settings.database_url.startswith("postgres://") or settings.database_url.startswith("postgresql://"):
        from cosmu.data.altdata import PgAltDataStore
        from cosmu.knowledge.store import Store

        return PgAltDataStore(Store(settings))
    return AltDataStore()


def _safe(source: str, fn: Callable[[], int]) -> int:
    """Run one source's ingest; a network failure / None is caught and logged as a 0 count so one dead
    source never aborts the pass. This is what makes the cron-able pass robust without a babysitter."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one dead source must never abort the whole pass
        logger.warning("ingest source %s failed (counted as 0): %s", source, exc)
        return 0


def run_once(store=None, *, symbols: list[str] | None = None, providers: Providers | None = None) -> dict[str, int]:  # noqa: ANN001
    """ONE append-only, point-in-time pass over the free sources into the alt-data store, composing the
    existing ingest_* primitives. Returns per-source append counts. Per-source failure → a 0 count, never
    an abort. The LLM runs ONLY at news standardization (cached); everything else is numeric (no LLM)."""
    store = store if store is not None else _default_store()
    # Accept a knowledge `Store` (the master tick hands one in): it has no append/read_asof, so wrap it as the
    # DB-backed central alt-data store — exactly what the API + research loop read from. Without this every
    # source raised `'Store' object has no attribute 'append'`, got swallowed as a 0 count, and the deployed
    # tick silently ingested nothing. An AltDataStore/PgAltDataStore (has `.append`) is used as-is.
    if not hasattr(store, "append"):
        from cosmu.data.altdata import PgAltDataStore

        store = PgAltDataStore(store)
    symbols = list(symbols) if symbols is not None else list(DEFAULT_SYMBOLS)
    p = providers if providers is not None else Providers.from_settings(get_settings())

    # Run-level cache: the single FRED provider feeds several semantic features off the SAME series
    # (VIXCLS → vix_level + vix_term_slope, T10Y2Y → macro_regime + yield_curve_2s10s). Memoize it so each
    # (symbol, series, limit) is fetched ONCE per pass — no redundant external calls within the run.
    fred = MemoizingProvider(p.fred)

    counts: dict[str, int] = {}
    counts["funding_rate"] = _safe(
        "funding_rate", lambda: ingest_numeric(store, p.funding, symbols, "funding_rate", provider_name="binance")
    )
    counts["okx_funding_rate"] = _safe(
        "okx_funding_rate",
        lambda: ingest_numeric(store, p.okx_funding, list(OKX_PERP_UNIVERSE), "funding_rate", provider_name="okx_perp"),
    )
    counts["kraken_futures_funding_rate"] = _safe(
        "kraken_futures_funding_rate",
        lambda: ingest_numeric(
            store, p.kraken_futures_funding, list(KRAKEN_FUTURES_UNIVERSE), "funding_rate", provider_name="kraken_futures"
        ),
    )
    # Fear & Greed and the cross-asset transfer series are market-wide → ingest once under the MARKET key.
    counts["fear_greed"] = _safe(
        "fear_greed", lambda: ingest_numeric(store, p.feargreed, ["MARKET"], "fear_greed", provider_name="alternative.me")
    )
    counts["news_sentiment"] = _safe(
        "news_sentiment", lambda: ingest_news_sentiment(store, p.news, symbols, llm=p.llm)
    )
    counts["macro_regime"] = _safe(
        "macro_regime",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric=p.fred_series, stored_metric="macro_regime", provider_name="fred"
        ),
    )
    counts["vix_level"] = _safe(
        "vix_level",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="VIXCLS", stored_metric="vix_level", provider_name="fred"
        ),
    )
    counts["fed_funds_rate"] = _safe(
        "fed_funds_rate",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="DFF", stored_metric="fed_funds_rate", provider_name="fred"
        ),
    )
    counts["defi_tvl"] = _safe(
        "defi_tvl",
        lambda: ingest_market_wide_numeric(
            store, p.defillama, source_metric="defi_tvl", stored_metric="defi_tvl", provider_name="defillama"
        ),
    )
    counts["risk_on"] = _safe(
        "risk_on",
        lambda: ingest_market_wide_numeric(
            store, p.polymarket, source_metric=p.polymarket_token, stored_metric="risk_on", provider_name="polymarket"
        ),
    )
    counts["liquidations"] = _safe("liquidations", lambda: ingest_liquidations(store, p.liquidations, symbols))
    counts["putcall_ratio"] = _safe("putcall_ratio", lambda: ingest_putcall(store, p.putcall))
    # FRED-derived macro features (key from env: FRED_API_KEY)
    counts["dxy"] = _safe(
        "dxy",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="DTWEXBGS", stored_metric="dxy", provider_name="fred"
        ),
    )
    counts["yield_curve_2s10s"] = _safe(
        "yield_curve_2s10s",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="T10Y2Y", stored_metric="yield_curve_2s10s", provider_name="fred"
        ),
    )
    counts["credit_spread"] = _safe(
        "credit_spread",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="BAMLH0A0HYM2", stored_metric="credit_spread", provider_name="fred"
        ),
    )
    counts["vix_term_slope"] = _safe(
        "vix_term_slope",
        lambda: ingest_market_wide_numeric(
            store, fred, source_metric="VIXCLS", stored_metric="vix_term_slope", provider_name="fred"
        ),
    )
    # Exchange-derived crypto features (free Binance fapi, no key)
    counts["open_interest"] = _safe(
        "open_interest", lambda: ingest_numeric(store, p.open_interest, symbols, "open_interest", provider_name="binance")
    )
    counts["perp_spot_basis"] = _safe(
        "perp_spot_basis", lambda: ingest_numeric(store, p.basis, symbols, "perp_spot_basis", provider_name="binance")
    )
    counts["exchange_netflow"] = _safe(
        "exchange_netflow", lambda: ingest_numeric(store, p.netflow, symbols, "exchange_netflow", provider_name="binance")
    )
    # OSINT (free OpenSky, low-confidence)
    counts["osint_air_activity"] = _safe(
        "osint_air_activity",
        lambda: ingest_market_wide_numeric(
            store, p.osint, source_metric="osint_air_activity", stored_metric="osint_air_activity", provider_name="opensky"
        ),
    )
    # Polymarket CLOB-derived (key from env: POLYMARKET_TOKEN)
    counts["pm_implied_prob"] = _safe(
        "pm_implied_prob",
        lambda: ingest_market_wide_numeric(
            store, p.polymarket_clob, source_metric="pm_implied_prob", stored_metric="pm_implied_prob", provider_name="polymarket"
        ),
    )
    counts["pm_prob_velocity"] = _safe(
        "pm_prob_velocity",
        lambda: ingest_market_wide_numeric(
            store, p.polymarket_clob, source_metric="pm_prob_velocity", stored_metric="pm_prob_velocity", provider_name="polymarket"
        ),
    )
    counts["pm_book_depth"] = _safe(
        "pm_book_depth",
        lambda: ingest_market_wide_numeric(
            store, p.polymarket_clob, source_metric="pm_book_depth", stored_metric="pm_book_depth", provider_name="polymarket"
        ),
    )
    # Social feeds (tier1, low-confidence). Reddit is market-wide (one crowd read under MARKET); LunarCrush is
    # per-crypto-symbol and key-gated (empty without LUNARCRUSH_API_KEY → counted 0, never an abort).
    counts["reddit_sentiment"] = _safe(
        "reddit_sentiment",
        lambda: ingest_market_wide_numeric(
            store, p.reddit, source_metric="reddit_sentiment", stored_metric="reddit_sentiment", provider_name="reddit"
        ),
    )
    counts["social_volume"] = _safe(
        "social_volume", lambda: ingest_numeric(store, p.lunarcrush, symbols, "social_volume", provider_name="lunarcrush")
    )
    counts["social_sentiment"] = _safe(
        "social_sentiment", lambda: ingest_numeric(store, p.lunarcrush, symbols, "social_sentiment", provider_name="lunarcrush")
    )
    counts["galaxy_score"] = _safe(
        "galaxy_score", lambda: ingest_numeric(store, p.lunarcrush, symbols, "galaxy_score", provider_name="lunarcrush")
    )
    # xAI/Grok Twitter sentiment (key-gated: no-op without XAI_API_KEY; market-wide, LLM scores text only).
    counts["twitter_sentiment"] = _safe(
        "twitter_sentiment",
        lambda: ingest_market_wide_numeric(
            store, p.xai_twitter, source_metric="twitter_sentiment", stored_metric="twitter_sentiment", provider_name="xai"
        ),
    )
    counts["twitter_influencer_sentiment"] = _safe(
        "twitter_influencer_sentiment",
        lambda: ingest_market_wide_numeric(
            store, p.xai_twitter, source_metric="twitter_influencer_sentiment", stored_metric="twitter_influencer_sentiment", provider_name="xai"
        ),
    )
    # Event/news scorer: typed, dated, point-in-time signal (sign × magnitude). The LLM standardizes text
    # ONLY at ingest (cached); the offline lexicon is used when no LLM key is set.
    counts["news_event_score"] = _safe(
        "news_event_score", lambda: ingest_news_event_score(store, p.news, symbols, llm=p.event_llm)
    )
    # EU-accessible, keyless: GDELT geopolitical news tone (market-wide) + Deribit DVOL (per-symbol BTC/ETH).
    counts["gdelt_tone"] = _safe(
        "gdelt_tone",
        lambda: ingest_market_wide_numeric(
            store, p.gdelt_tone, source_metric="gdelt_tone", stored_metric="gdelt_tone", provider_name="gdelt"
        ),
    )
    counts["dvol"] = _safe(
        "dvol", lambda: ingest_numeric(store, p.dvol, symbols, "dvol", provider_name="deribit")
    )
    # LLM qualitative→quantitative index scores: each is market-wide, ingested once under the MARKET key under
    # its own SEMANTIC name. Key-gated (no LLM key → the provider returns [] → counted 0, never an abort). The
    # LLM only proposes the rubric-anchored number at ingest; the deterministic Gate alone disposes.
    for _index in INDEX_RUBRICS:
        counts[_index] = _safe(
            _index,
            lambda m=_index: ingest_market_wide_numeric(
                store, p.llm_index, source_metric=m, stored_metric=m, provider_name="llm_index"
            ),
        )
    # Cross-asset daily price levels (free, no key): metals / commodities / equity indexes / FX. Each is
    # market-wide (ingested once under the MARKET key under its SEMANTIC name). Numeric → no LLM.
    for _metric in MULTIASSET_METRICS:
        counts[_metric] = _safe(
            _metric,
            lambda m=_metric: ingest_market_wide_numeric(
                store, p.multiasset, source_metric=m, stored_metric=m, provider_name="stooq"
            ),
        )
    # Venue fees: account-specific maker/taker PIT snapshot. Key-gated: offline/no-key → static-catalog
    # fallback is used, so the cron never crashes. Stored under provider="venue_fees",
    # symbol="<venue_id>:<symbol>", metric="venue_fees_maker"|"venue_fees_taker".
    counts["venue_fees"] = _safe(
        "venue_fees", lambda: _ingest_venue_fees(store, p.venue_fees, symbols)
    )
    return counts


def _ingest_venue_fees(store, provider: AltDataProvider, symbols: list[str]) -> int:
    """Snapshot venue fees for every tracked symbol into the alt_data store.
    Each symbol gets two rows: venue_fees_maker and venue_fees_taker.
    The store key is ``symbol="<venue_id>:<symbol>"`` so multi-venue can coexist."""
    from datetime import datetime, UTC
    from cosmu.data.altdata import AltDataPoint

    # Determine the venue_id from the provider (default "binance").
    venue_id = getattr(provider, "exchange_id", "binance")
    total = 0
    for symbol in symbols:
        for metric in ("venue_fees_maker", "venue_fees_taker"):
            pts = provider.fetch_series(symbol, metric, limit=1)
            if pts:
                store_symbol = f"{venue_id}:{symbol}"
                store.append("venue_fees", store_symbol, metric, pts)
                total += len(pts)
    return total


def _run_passes(passes: int) -> dict[str, int]:
    """Run N bounded passes (default 1). Append-only means a re-run is just more rows; the point-in-time
    view is unchanged. Returns the LAST pass's counts (what `python3 -m cosmu.ingest.run` prints)."""
    last: dict[str, int] = {}
    for i in range(max(1, passes)):
        last = run_once()
        if passes > 1:
            print(f"pass {i + 1}/{passes}: {last}")
    return last


def _main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="One-pass free-data ingest into the alt-data store (no keys).")
    parser.add_argument("--passes", type=int, default=1, help="number of bounded passes to run (default 1)")
    args = parser.parse_args(argv)

    counts = _run_passes(args.passes)
    print("FREE-DATA INGEST — one pass complete")
    for source, n in counts.items():
        print(f"  {source:<15} {n:>6} points")
    total = sum(counts.values())
    print(f"  {'TOTAL':<15} {total:>6} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
