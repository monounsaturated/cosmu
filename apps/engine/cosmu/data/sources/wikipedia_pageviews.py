# intent: Wikipedia Pageviews — a free, no-key, EXCELLENT point-in-time attention signal. Uses the
# Wikimedia REST Pageviews API (wikimedia.org/api/rest_v1/metrics/pageviews) to fetch daily view
# counts for entity articles (e.g. "Bitcoin", "Tesla,_Inc.", "S&P_500"). Published with a ~1 day lag
# (the API makes day T viewcount knowable on day T+1 ≥ 00:00 UTC), so available_at = obs_date + 1 day
# (00:00 UTC). This is one of the CLEANEST honest sources: counts are immutable (no revision), free,
# open, and truly causal — you see day-T views on day T+1, never before.
#
# PIT contract:
#   ts           = midnight UTC on the observation day (the day the views were recorded)
#   available_at = ts + 1 day (the first moment the API would return this count, given ~1d lag)
#   gap          = absent AltDataPoint, NEVER zero-filled — a missing day is unknown, not zero
#   revisions    = Wikimedia does NOT revise historical counts; appended data is stable
#
# Offline testability: inject _fetcher(url) -> dict so the entire HTTP path is mockable. Tests run
# with a bundled fixture — no network, no key, no CI flakiness.
#
# Three features (stored under provider="wikimedia"):
#   wiki_pageviews        — raw daily view count for the article
#   wiki_pageviews_log    — natural log of view count (stabilizes variance across articles of different scale)
#   wiki_pageviews_zscore — 30-day trailing z-score of log views (surface attention spikes in-context)
#
# The per-symbol entity name is looked up via ENTITY_MAP (overridable). Unknown symbols fall back
# to a best-effort "<BaseAsset>" lookup (e.g. "BTCUSDT" → "Bitcoin"). A None map entry disables the
# source for that symbol (returns None values, not a crash).

from __future__ import annotations

import math
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the log/zscore formula changes so a gate-passed survivor stays re-runnable.
TRANSFORM_VERSION = "wiki-pageviews-v1"

# Wikimedia REST API base — free, no key, no rate-limit for reasonable crawl rates.
_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents"

# Availability lag: daily page-view counts for day T are published with a ~1-day lag.
# We conservatively stamp available_at = midnight of T+1 (the opening moment of the NEXT UTC day).
_AVAILABILITY_LAG = timedelta(days=1)

# 30-day window for the trailing z-score denominator. Chosen to be long enough to be stable but
# short enough to adapt to regime shifts in attention (a product going viral changes its base rate).
_ZSCORE_WINDOW = 30

# Canonical entity map: symbol (as queried by the gate, e.g. "BTCUSDT") → Wikipedia article title
# (underscore-encoded; case-sensitive). None = source disabled for that symbol (returns None gracefully).
# Extend this map to add new entities without touching the adapter logic.
ENTITY_MAP: dict[str, str | None] = {
    # --- crypto (spot pairs keyed as Binance uses them) ---
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "BNBUSDT": "Binance_(company)",
    "SOLUSDT": "Solana_(blockchain_platform)",
    "XRPUSDT": "XRP_(cryptocurrency)",
    "DOGEUSDT": "Dogecoin",
    "ADAUSDT": "Cardano_(blockchain_platform)",
    "AVAXUSDT": "Avalanche_(blockchain_platform)",
    "LINKUSDT": "Chainlink_(blockchain)",
    "DOTUSDT": "Polkadot_(cryptocurrency)",
    "MATICUSDT": "Polygon_(blockchain)",
    "LTCUSDT": "Litecoin",
    "ATOMUSDT": "Cosmos_(blockchain)",
    "NEARUSDT": "NEAR_Protocol",
    "FTMUSDT": "Fantom_(blockchain)",
    # --- equity (ticker → canonical Wikipedia article) ---
    "AAPL": "Apple_Inc.",
    "TSLA": "Tesla,_Inc.",
    "NVDA": "Nvidia",
    "MSFT": "Microsoft",
    "AMZN": "Amazon_(company)",
    "GOOG": "Google",
    "META": "Meta_Platforms",
    "NFLX": "Netflix",
    # --- macro (market-wide "MARKET" scope + commonly queried macro articles) ---
    "MARKET": "S&P_500",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
}

# Base-asset fallback map: strip trailing "USDT"/"USDC"/"BTC" and try a well-known common-name.
_BASE_ASSET_FALLBACK: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "BNB": "Binance_(company)",
    "SOL": "Solana_(blockchain_platform)",
    "XRP": "XRP_(cryptocurrency)",
    "DOGE": "Dogecoin",
    "ADA": "Cardano_(blockchain_platform)",
    "AVAX": "Avalanche_(blockchain_platform)",
    "LINK": "Chainlink_(blockchain)",
    "DOT": "Polkadot_(cryptocurrency)",
    "MATIC": "Polygon_(blockchain)",
    "LTC": "Litecoin",
    "ATOM": "Cosmos_(blockchain)",
    "NEAR": "NEAR_Protocol",
    "FTM": "Fantom_(blockchain)",
}


def _article_for_symbol(symbol: str) -> str | None:
    """Resolve symbol → Wikipedia article title. Returns None if the source is disabled for this symbol."""
    if symbol in ENTITY_MAP:
        return ENTITY_MAP[symbol]
    # Strip common quote-currency suffixes and retry the fallback map.
    for suffix in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
        if symbol.endswith(suffix):
            base = symbol[: -len(suffix)]
            if base in _BASE_ASSET_FALLBACK:
                return _BASE_ASSET_FALLBACK[base]
    return None  # unknown; caller returns None gracefully


def _url_for_article(article: str, start: str, end: str) -> str:
    """Wikimedia pageviews URL for one article over a daily date range.
    start/end are YYYYMMDD strings (inclusive, daily granularity)."""
    return f"{_API_BASE}/{article}/daily/{start}/{end}"


def _parse_response(payload: dict) -> list[AltDataPoint]:
    """Parse a Wikimedia pageviews API response into AltDataPoints.

    PIT contract:
      ts           = midnight UTC on the recorded day
      available_at = ts + 1 day (the earliest the count is knowable — published with ~1d lag)
      gap          = absent point, never zero
    The API returns 'items': [{"timestamp": "YYYYMMDDH0", "views": N}, ...]."""
    items = payload.get("items") or []
    out: list[AltDataPoint] = []
    for item in items:
        raw_ts = item.get("timestamp")
        views = item.get("views")
        if not raw_ts or views is None:
            continue
        try:
            # Wikimedia timestamps look like "2024010100" (YYYYMMDDH0 — always "00" for daily).
            ts = datetime(
                int(raw_ts[0:4]),
                int(raw_ts[4:6]),
                int(raw_ts[6:8]),
                tzinfo=UTC,
            )
            available_at = ts + _AVAILABILITY_LAG  # day T+1 midnight UTC — first knowable moment
            out.append(AltDataPoint(ts=ts, available_at=available_at, value=float(views)))
        except (ValueError, IndexError):
            continue
    return sorted(out, key=lambda p: p.ts)


class WikipediaPageviewsSource:
    """Daily Wikipedia page-view counts per entity article — free, no key, honest PIT.

    Three features keyed by `metric` kwarg (passed through the DataSource protocol):
      wiki_pageviews        — raw daily view count (integer, as float)
      wiki_pageviews_log    — natural log of the count (ln(views); stabilizes scale disparities)
      wiki_pageviews_zscore — 30-day trailing z-score of wiki_pageviews_log
                              (surfaces an attention SPIKE relative to recent baseline)

    PIT contract: available_at = ts + 1 day (conservative 1-day lag; Wikimedia publishes day T on day T+1).
    No revisions: Wikimedia does not rewrite historical counts — the series is stable once published.
    Gaps are absent AltDataPoints (never zero-fabricated).

    The article title for a symbol is resolved via ENTITY_MAP (exact), then a base-asset strip+fallback.
    An unknown symbol returns a None-valued SourceFeature — never crashes the gate pass.

    Offline testability: inject _fetcher(url)->dict in the constructor. All HTTP is isolated behind
    that single callable, so tests are fully deterministic without a network key or monkeypatching."""

    name: str = "wiki_pageviews"
    kind: SourceKind = "social"
    metric: str = "wiki_pageviews"
    prior: str = (
        "Wikipedia article page-view count is a clean, free, causal attention signal: "
        "it is knowable on day T+1 (the API publishes day-T counts with ~1d lag), immutable once published, "
        "and covers a wide universe of assets via their canonical Wikipedia articles. "
        "An attention SPIKE (large z-score of log views) may precede or coincide with price moves — "
        "crowd search attention often leads price, especially at the onset of a narrative. "
        "Low-confidence until validated OOS."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.45  # tier1 / low-confidence — must earn its place via OOS
    lookback_days: int = 90  # how many trailing days of raw data to fetch per call

    def __init__(
        self,
        *,
        metric: str = "wiki_pageviews",
        lookback_days: int = 90,
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self.metric = metric
        self.lookback_days = lookback_days
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1 (contact.moncory@gmail.com)"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            import json

            return json.loads(resp.read().decode("utf-8"))

    def fetch_raw_series(self, symbol: str, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch raw pageview AltDataPoints for `symbol` whose available_at <= as_of.

        A gap (no data for a day) is ABSENT from the returned list — never zero-fabricated.
        Returns [] if the symbol is unknown or the API fails."""
        article = _article_for_symbol(symbol)
        if article is None:
            return []

        # Fetch a trailing window ending at as_of.  We request from (as_of - lookback_days) to
        # (as_of - 1 day) — the last full day that COULD be available given the 1-day lag.
        end_day = as_of - _AVAILABILITY_LAG  # last day knowable at as_of
        start_day = end_day - timedelta(days=self.lookback_days - 1)
        start_str = start_day.strftime("%Y%m%d")
        end_str = end_day.strftime("%Y%m%d")
        url = _url_for_article(article, start_str, end_str)
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash
            return []

        raw = _parse_response(payload)
        # Filter to strictly point-in-time: only points whose available_at <= as_of.
        pts = [p for p in raw if p.available_at <= as_of]
        return pts[-limit:]

    def _derive_metric(self, raw: list[AltDataPoint], metric: str) -> list[AltDataPoint]:
        """Derive wiki_pageviews_log or wiki_pageviews_zscore from raw viewcount series.

        Gaps in the raw series remain gaps in the derived series — never zero-filled.
        The zscore uses only the trailing _ZSCORE_WINDOW points (strictly causal)."""
        if metric == "wiki_pageviews":
            return raw

        # log transform — skip points with views <= 0 (shouldn't happen, but be safe)
        log_pts = [
            AltDataPoint(ts=p.ts, available_at=p.available_at, value=math.log(p.value))
            for p in raw
            if p.value > 0
        ]
        if metric == "wiki_pageviews_log":
            return log_pts

        # wiki_pageviews_zscore: trailing 30d z of log(views). Each point's z-score uses only
        # points whose available_at < that point's available_at (strictly causal — no look-ahead).
        if metric == "wiki_pageviews_zscore":
            out: list[AltDataPoint] = []
            for i, pt in enumerate(log_pts):
                # window = the _ZSCORE_WINDOW prior log points (strictly before this one)
                window = [p.value for p in log_pts[max(0, i - _ZSCORE_WINDOW) : i]]
                if len(window) < 2:
                    continue  # not enough history — absent, not zero
                mu = sum(window) / len(window)
                var = sum((v - mu) ** 2 for v in window) / (len(window) - 1)
                std = math.sqrt(var) if var > 0 else None
                if std is None or std == 0:
                    continue  # zero variance (constant views window) — absent, not fabricated
                z = (pt.value - mu) / std
                out.append(AltDataPoint(ts=pt.ts, available_at=pt.available_at, value=z))
            return out

        return []  # unknown metric → absent

    def backfill(self, symbol: str, days: int, *, as_of: datetime | None = None, limit: int = 4096) -> list[AltDataPoint]:
        """Pull `days` of derived-metric history for `symbol` as point-in-time AltDataPoints.

        The Wikimedia REST API serves a [start, end] daily date range per article in ONE request, so a
        400-day backfill is a single network call (not 400). The returned series is the FULL derived
        metric (raw / log / 30d-zscore) over the window — every day whose available_at <= as_of —
        not just the latest point.

        PIT honesty (identical to query):
          - available_at = ts + 1 day (Wikimedia publishes day-T counts on day T+1).
          - Only points with available_at <= as_of are returned (no look-ahead).
          - A gap (missing day) is ABSENT from the series — never zero-filled. The z-score variant
            additionally drops any day with < 2 prior points of history (insufficient window).
        Unknown symbol or fetch failure → [] (never raises, never fabricates).
        """
        now = as_of or datetime.now(tz=UTC)
        article = _article_for_symbol(symbol)
        if article is None:
            return []
        end_day = now - _AVAILABILITY_LAG  # last day knowable at now
        start_day = end_day - timedelta(days=max(0, days - 1))
        start_str = start_day.strftime("%Y%m%d")
        end_str = end_day.strftime("%Y%m%d")
        url = _url_for_article(article, start_str, end_str)
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash a backfill
            return []
        raw = [p for p in _parse_response(payload) if p.available_at <= now]
        derived = self._derive_metric(raw, self.metric)
        return [p for p in derived if p.available_at <= now][-limit:]

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest derived metric value for `scope` whose available_at <= as_of (point-in-time, no look-ahead).

        Returns a None-valued SourceFeature if the symbol is unknown, the API is unreachable,
        or there is insufficient history for the z-score window — NEVER raises, NEVER fabricates."""
        raw = self.fetch_raw_series(scope, as_of, limit=limit)
        derived = self._derive_metric(raw, self.metric)

        latest: AltDataPoint | None = None
        for p in derived:
            if p.available_at <= as_of:
                latest = p  # ascending, so the last valid one is the latest

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
            observed_ts=latest.ts if latest else None,  # true obs day (distinct from the +1d availability)
        )


__all__ = [
    "ENTITY_MAP",
    "TRANSFORM_VERSION",
    "WikipediaPageviewsSource",
    "_article_for_symbol",
    "_parse_response",
]
