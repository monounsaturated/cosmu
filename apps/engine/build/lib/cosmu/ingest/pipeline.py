# intent: scheduled free-data ingestion → the append-only, point-in-time alt-data store; inputs: free providers (funding/OI, Fear&Greed, news headlines); outputs: stored snapshots (numeric + LLM-standardized news sentiment) the real gate reads; invariants: APIs not scraping, append-only (vendor revisions never overwrite), LLM runs ONLY here (news→sentiment, cached), idempotent (re-runs don't change the point-in-time view), offline-safe via injected providers.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cosmu.data.altdata import AltDataProvider, AltDataStore, NewsProvider
from cosmu.ingest.standardize import StandardizedNews, standardize_news


@dataclass(frozen=True)
class IngestSummary:
    counts: dict[str, int]


def ingest_numeric(alt_store: AltDataStore, provider: AltDataProvider, symbols: list[str], metric: str, *, provider_name: str, limit: int = 1000) -> int:
    """Pull a numeric metric for each symbol and append it point-in-time. No LLM."""
    total = 0
    for symbol in symbols:
        points = provider.fetch_series(symbol, metric, limit=limit)
        if points:
            alt_store.append(provider_name, symbol, metric, points)
            total += len(points)
    return total


def ingest_news_sentiment(
    alt_store: AltDataStore,
    news_provider: NewsProvider,
    symbols: list[str],
    *,
    provider_name: str = "news",
    limit: int = 500,
    llm: Callable[[str], StandardizedNews] | None = None,
) -> int:
    """Pull headlines and standardize them to a numeric `news_sentiment` series — the ONLY place the
    LLM runs. Content-hash cache is shared across symbols so a wire-service repeat costs nothing."""
    cache: dict = {}
    total = 0
    for symbol in symbols:
        points = standardize_news(news_provider.fetch_news(symbol, limit=limit), cache=cache, llm=llm)
        if points:
            alt_store.append(provider_name, symbol, "news_sentiment", points)
            total += len(points)
    return total


def ingest_market_wide_numeric(
    alt_store: AltDataStore,
    provider: AltDataProvider,
    *,
    source_metric: str,
    stored_metric: str,
    provider_name: str,
    limit: int = 1000,
) -> int:
    """Pull a market-wide numeric series by its provider-native id (`source_metric`, e.g. a FRED series id
    or a Polymarket token id) and append it point-in-time under its SEMANTIC name (`stored_metric`, e.g.
    macro_regime / risk_on) at the MARKET key. The native→semantic mapping lives here, at ingest. No LLM."""
    points = provider.fetch_series("MARKET", source_metric, limit=limit)
    if points:
        alt_store.append(provider_name, "MARKET", stored_metric, points)
    return len(points)


def ingest_free_sources(
    alt_store: AltDataStore,
    *,
    funding_provider: AltDataProvider,
    feargreed_provider: AltDataProvider,
    news_provider: NewsProvider,
    symbols: list[str],
    llm: Callable[[str], StandardizedNews] | None = None,
) -> IngestSummary:
    """One pass over the free single-asset sources (#2–#5 in PLAN §9). Safe to run on a schedule —
    append-only + point-in-time means re-runs never rewrite history."""
    counts = {
        "funding_rate": ingest_numeric(alt_store, funding_provider, symbols, "funding_rate", provider_name="binance"),
        # Fear & Greed is market-wide — ingest once under a MARKET key, not per symbol.
        "fear_greed": ingest_numeric(alt_store, feargreed_provider, ["MARKET"], "fear_greed", provider_name="alternative.me"),
        "news_sentiment": ingest_news_sentiment(alt_store, news_provider, symbols, llm=llm),
    }
    return IngestSummary(counts=counts)


def ingest_liquidations(alt_store: AltDataStore, provider: AltDataProvider, symbols: list[str], *, provider_name: str = "coinglass", limit: int = 1000) -> int:
    """Pull per-crypto-symbol total liquidations (long+short USD) point-in-time. Numeric → no LLM.
    Thin wrapper over ingest_numeric so the scheduled pass + tests read the same primitive."""
    return ingest_numeric(alt_store, provider, symbols, "liquidations", provider_name=provider_name, limit=limit)


def ingest_putcall(alt_store: AltDataStore, provider: AltDataProvider, *, provider_name: str = "cboe", limit: int = 1000) -> int:
    """Pull the market-wide CBOE put/call ratio under the MARKET key, point-in-time. Numeric → no LLM."""
    return ingest_market_wide_numeric(
        alt_store, provider, source_metric="putcall_ratio", stored_metric="putcall_ratio", provider_name=provider_name, limit=limit,
    )


def ingest_extra_free_sources(
    alt_store: AltDataStore,
    *,
    liquidation_provider: AltDataProvider,
    putcall_provider: AltDataProvider,
    news_provider: NewsProvider,
    symbols: list[str],
    llm: Callable[[str], StandardizedNews] | None = None,
) -> IngestSummary:
    """One scheduled pass over the NEW real free sources (Coinglass liquidations per crypto symbol,
    CBOE put/call market-wide, GDELT real news → standardized sentiment). Append-only + point-in-time, so
    re-runs never rewrite the view. Offline-safe via injected providers (fixtures in tests)."""
    counts = {
        "liquidations": ingest_liquidations(alt_store, liquidation_provider, symbols),
        "putcall_ratio": ingest_putcall(alt_store, putcall_provider),
        "news_sentiment": ingest_news_sentiment(alt_store, news_provider, symbols, llm=llm),
    }
    return IngestSummary(counts=counts)


def ingest_cross_asset_sources(
    alt_store: AltDataStore,
    *,
    funding_provider: AltDataProvider,
    feargreed_provider: AltDataProvider,
    news_provider: NewsProvider,
    fred_provider: AltDataProvider,
    polymarket_provider: AltDataProvider,
    symbols: list[str],
    fred_series: str,
    polymarket_token: str,
    llm: Callable[[str], StandardizedNews] | None = None,
) -> IngestSummary:
    """Phase 1.6: the single-asset free sources PLUS the two cross-asset transfer series — FRED macro
    (→ macro_regime) and Polymarket odds (→ risk_on). All numeric except news (LLM only there, cached).
    This is the seam a scheduled worker fills so `evaluate_cross_asset_ablation` runs on real free data."""
    summary = ingest_free_sources(
        alt_store, funding_provider=funding_provider, feargreed_provider=feargreed_provider,
        news_provider=news_provider, symbols=symbols, llm=llm,
    )
    summary.counts["macro_regime"] = ingest_market_wide_numeric(
        alt_store, fred_provider, source_metric=fred_series, stored_metric="macro_regime", provider_name="fred",
    )
    summary.counts["risk_on"] = ingest_market_wide_numeric(
        alt_store, polymarket_provider, source_metric=polymarket_token, stored_metric="risk_on", provider_name="polymarket",
    )
    return summary
