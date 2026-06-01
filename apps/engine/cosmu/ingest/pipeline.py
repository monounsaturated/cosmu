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


def ingest_free_sources(
    alt_store: AltDataStore,
    *,
    funding_provider: AltDataProvider,
    feargreed_provider: AltDataProvider,
    news_provider: NewsProvider,
    symbols: list[str],
    llm: Callable[[str], StandardizedNews] | None = None,
) -> IngestSummary:
    """One pass over the free sources (#2–#5 in PLAN §9). Safe to run on a schedule — append-only
    + point-in-time means re-runs never rewrite history."""
    counts = {
        "funding_rate": ingest_numeric(alt_store, funding_provider, symbols, "funding_rate", provider_name="binance"),
        # Fear & Greed is market-wide — ingest once under a MARKET key, not per symbol.
        "fear_greed": ingest_numeric(alt_store, feargreed_provider, ["MARKET"], "fear_greed", provider_name="alternative.me"),
        "news_sentiment": ingest_news_sentiment(alt_store, news_provider, symbols, llm=llm),
    }
    return IngestSummary(counts=counts)
