# intent: scheduled free-data ingestion → the append-only, point-in-time alt-data store; inputs: free providers (funding/OI, Fear&Greed, news headlines); outputs: stored snapshots (numeric + LLM-standardized news sentiment) the real gate reads; invariants: APIs not scraping, append-only (vendor revisions never overwrite), LLM runs ONLY here (news→sentiment, cached), idempotent (re-runs don't change the point-in-time view), offline-safe via injected providers.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from cosmu.data.altdata import AltDataPoint, AltDataProvider, AltDataStore, NewsProvider
from cosmu.ingest.standardize import (
    NewsEventScore,
    StandardizedNews,
    score_news_events,
    scored_events_to_altdata,
    standardize_news,
)


@dataclass(frozen=True)
class IngestSummary:
    counts: dict[str, int]


class MemoizingProvider:
    """Wraps an AltDataProvider so each (symbol, metric, limit) is fetched AT MOST ONCE per run — the
    run-level cache that kills redundant external calls. The clearest win: a single FRED provider feeds
    several semantic features off the SAME series (T10Y2Y → macro_regime + yield_curve_2s10s); without
    memoization that is two live calls per shared series. The
    cache lives for the wrapper's lifetime (one ingest pass), so a fresh run always re-pulls fresh data."""

    def __init__(self, inner: AltDataProvider) -> None:
        self._inner = inner
        self._cache: dict[tuple[str, str, int], list[AltDataPoint]] = {}
        self.calls = 0  # number of times the INNER provider was actually hit (cache misses)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        key = (symbol, metric, limit)
        if key not in self._cache:
            self.calls += 1
            self._cache[key] = self._inner.fetch_series(symbol, metric, limit=limit)
        return self._cache[key]


def append_dedup(alt_store: AltDataStore, provider_name: str, symbol: str, metric: str, points: list[AltDataPoint]) -> int:
    """Append only points whose `ts` is not already stored for (provider, symbol, metric) — the idempotent
    backfill primitive. The store is append-only, so a naive re-run would double-write every funding instant;
    this reads the existing ts set ONCE and writes only genuinely-new points. Dedup key is
    (provider, symbol, metric, ts). Returns the count of NEW points written (0 on a no-op re-run)."""
    if not points:
        return 0
    existing = {p.ts for p in alt_store.read_all(provider_name, symbol, metric)}
    fresh = [p for p in points if p.ts not in existing]
    if fresh:
        alt_store.append(provider_name, symbol, metric, fresh)
    return len(fresh)


def _append_fresh(alt_store: AltDataStore, provider_name: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
    """Append only points whose (ts, available_at) pair is not already stored — the idempotent primitive for
    the SCHEDULED ingest paths below, which re-pull a full provider window every cron pass. Unlike
    `append_dedup` (ts-only key, for backfills of revision-free series) this keeps genuine vendor revisions
    (same ts, later available_at). Without it every 15-min pass appended a full duplicate copy of the window:
    unbounded alt_data growth, AND the `[-limit:]` read slice in StoreBackedAltProvider covered ever-less
    DISTINCT history — the gate silently saw days of unique data where it asked for years."""
    if not points:
        return
    existing = {(p.ts, p.available_at) for p in alt_store.read_all(provider_name, symbol, metric)}
    fresh = [p for p in points if (p.ts, p.available_at) not in existing]
    if fresh:
        alt_store.append(provider_name, symbol, metric, fresh)


@dataclass(frozen=True)
class BackfillResult:
    """Per-symbol outcome of a funding backfill: how many NEW points landed and the span covered."""

    symbol: str
    written: int                 # NEW points appended this run (0 on an idempotent re-run)
    total: int                   # total points the provider returned for the window
    start: datetime | None       # earliest funding ts in the returned span
    end: datetime | None         # latest funding ts in the returned span

    @property
    def span_days(self) -> float:
        if self.start is None or self.end is None:
            return 0.0
        return (self.end - self.start).total_seconds() / 86400.0


def backfill_funding(
    alt_store: AltDataStore,
    provider: AltDataProvider,  # must expose `fetch_history(symbol, *, start_ms, end_ms=None)`
    symbols: list[str],
    *,
    start_ms: int,
    end_ms: int | None = None,
    provider_name: str = "binance",
    metric: str = "funding_rate",
) -> dict[str, BackfillResult]:
    """Backfill historical funding per symbol via a PAGINATED provider, append-only + dedup. Each symbol is
    fetched ONCE (the provider paginates internally — no redundant external calls), then written through
    `append_dedup` so a re-run writes 0 (idempotent on (provider, symbol, metric, ts)). Returns a per-symbol
    BackfillResult carrying the new-points count and the covered span."""
    results: dict[str, BackfillResult] = {}
    for symbol in symbols:
        points = provider.fetch_history(symbol, start_ms=start_ms, end_ms=end_ms)
        written = append_dedup(alt_store, provider_name, symbol, metric, points)
        start = points[0].ts if points else None
        end = points[-1].ts if points else None
        results[symbol] = BackfillResult(symbol=symbol, written=written, total=len(points), start=start, end=end)
    return results


def ingest_numeric(alt_store: AltDataStore, provider: AltDataProvider, symbols: list[str], metric: str, *, provider_name: str, limit: int = 1000) -> int:
    """Pull a numeric metric for each symbol and append it point-in-time. No LLM. Returns the number of
    points the provider SERVED (the source-liveness signal the tick's recommendations watch — 0 means the
    source returned nothing); only genuinely-new (ts, available_at) rows are appended."""
    total = 0
    for symbol in symbols:
        points = provider.fetch_series(symbol, metric, limit=limit)
        if points:
            _append_fresh(alt_store, provider_name, symbol, metric, points)
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
            _append_fresh(alt_store, provider_name, symbol, "news_sentiment", points)
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
        _append_fresh(alt_store, provider_name, "MARKET", stored_metric, points)
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


def ingest_news_event_score(
    alt_store: AltDataStore,
    news_provider: NewsProvider,
    symbols: list[str],
    *,
    provider_name: str = "news",
    limit: int = 500,
    llm: Callable[[str], NewsEventScore] | None = None,
) -> int:
    """Score headlines into typed point-in-time `news_event_score` (sign × magnitude) and store them.

    The LLM (when present) ONLY standardizes the text — it is NEVER on the gate/scoring/money path.
    Content-hash cached across symbols so a repeated headline costs nothing. Offline path uses the
    deterministic lexicon scorer. Returns the total number of scored points appended."""
    cache: dict = {}
    total = 0
    for symbol in symbols:
        events = score_news_events(news_provider.fetch_news(symbol, limit=limit), cache=cache, llm=llm)
        points = scored_events_to_altdata(events)
        if points:
            _append_fresh(alt_store, provider_name, symbol, "news_event_score", points)
            total += len(points)
    return total


def ingest_liquidations(alt_store: AltDataStore, provider: AltDataProvider, symbols: list[str], *, provider_name: str = "coinglass", limit: int = 1000) -> int:
    """Pull per-crypto-symbol total liquidations (long+short USD) point-in-time. Numeric → no LLM.
    The Coinglass provider exposes the data as metric="liquidations"; we store it under the canonical
    registry name "liquidation_cascade" so backtest wiring is consistent with feature_registry.py."""
    total = 0
    for symbol in symbols:
        points = provider.fetch_series(symbol, "liquidations", limit=limit)
        if points:
            _append_fresh(alt_store, provider_name, symbol, "liquidation_cascade", points)
            total += len(points)
    return total


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
        "liquidation_cascade": ingest_liquidations(alt_store, liquidation_provider, symbols),
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
    summary.counts["pm_risk_on"] = ingest_market_wide_numeric(
        alt_store, polymarket_provider, source_metric=polymarket_token, stored_metric="pm_risk_on", provider_name="polymarket",
    )
    return summary
