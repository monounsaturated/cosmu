# intent: GDELT 2.0 DOC API — a FREE, no-key, daily NEWS-VOLUME count DataSource. Pulls the raw daily
# count of news articles matching a per-topic query from the public GDELT DOC 2.0 timeline endpoint and
# turns it into a named, point-in-time, availability-stamped numeric feature. This is COUNTS ONLY (no
# tone, no LLM, no narrative parsing) — the deep narrative axis is intentionally closed; raw article
# counts are a cheap, orthogonal attention/coverage feature ("how much is the global press writing about
# Bitcoin today?").
#
# PIT CONTRACT (read before touching):
#   ts           = midnight UTC of the observation day (the day the articles were published)
#   available_at = ts + 1 day at 00:00 UTC
#                  GDELT updates every 15 minutes, but a FULL UTC day's count is only complete after the
#                  day closes; we conservatively stamp next-day so a day-T count is usable only from T+1
#                  00:00 UTC onward. NO LOOK-AHEAD.
#   as_of        = a query returns the latest day whose available_at ≤ as_of.
#   gaps         = a missing day is ABSENT (value=None), NEVER zero-filled. A gap is unknown coverage,
#                  not "zero articles" (GDELT outages / query holes are gaps, not real zeros).
#   revisions    = GDELT appends; we treat the next-day-stamped count as final and do not rewrite banked
#                  history (the 1-day lag absorbs intra-day appends).
#
# Offline testability: inject _fetcher(url)->dict so the entire HTTP path is mockable. Tests run with a
# bundled fixture — no network, no key, deterministic, no CI flakiness.
#
# Per-topic queries are looked up via TOPIC_MAP (symbol → GDELT query string). Unknown symbols fall back
# to a base-asset strip (e.g. "BTCUSDT" → "BTC" → "bitcoin"). A None map entry disables the source for
# that symbol (returns None values, not a crash).
#
# Confidence is low — news-volume counts are an exploratory orthogonal attention feature that must earn
# their place via OOS. The Gate is the disposal layer.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse/availability/query logic changes so a gate-passed
# survivor stays byte-for-byte re-runnable.
TRANSFORM_VERSION = "gdelt-counts-v1"

# GDELT DOC 2.0 API base — free, no key. mode=timelinevolraw → raw per-day article COUNTS (not tone).
_API_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# Availability lag: a full UTC day's article count is only complete after the day closes. We stamp
# available_at = midnight of T+1 (the opening moment of the NEXT UTC day) — conservative, never early.
_AVAILABILITY_LAG = timedelta(days=1)

# Canonical topic map: symbol (as the gate queries it, e.g. "BTCUSDT") → GDELT DOC query string.
# Quoted phrases keep multi-word topics intact. None = source disabled for that symbol (returns None).
# Extend this map to add new topics without touching the adapter logic.
TOPIC_MAP: dict[str, str | None] = {
    # --- crypto ---
    "BTCUSDT": '"bitcoin"',
    "ETHUSDT": '"ethereum"',
    "BNBUSDT": '"binance"',
    "SOLUSDT": '"solana"',
    "XRPUSDT": '("xrp" OR "ripple cryptocurrency")',
    "DOGEUSDT": '"dogecoin"',
    "ADAUSDT": '"cardano"',
    "AVAXUSDT": '"avalanche crypto"',
    "LINKUSDT": '"chainlink crypto"',
    "DOTUSDT": '"polkadot"',
    # --- macro / market-wide ---
    "MARKET": '("stock market" OR "financial markets")',
    "BTC": '"bitcoin"',
    "ETH": '"ethereum"',
}

# Base-asset fallback: strip a quote-currency suffix and map the bare asset to a query.
_BASE_ASSET_FALLBACK: dict[str, str] = {
    "BTC": '"bitcoin"',
    "ETH": '"ethereum"',
    "BNB": '"binance"',
    "SOL": '"solana"',
    "XRP": '("xrp" OR "ripple cryptocurrency")',
    "DOGE": '"dogecoin"',
    "ADA": '"cardano"',
    "AVAX": '"avalanche crypto"',
    "LINK": '"chainlink crypto"',
    "DOT": '"polkadot"',
}


def _query_for_symbol(symbol: str) -> str | None:
    """Resolve symbol → GDELT DOC query string. Returns None if the source is disabled for this symbol."""
    if symbol in TOPIC_MAP:
        return TOPIC_MAP[symbol]
    for suffix in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
        if symbol.endswith(suffix):
            base = symbol[: -len(suffix)]
            if base in _BASE_ASSET_FALLBACK:
                return _BASE_ASSET_FALLBACK[base]
    return None  # unknown; caller returns None gracefully


def _gdelt_dt(value: datetime) -> str:
    """Format a datetime as GDELT's compact stamp: YYYYMMDDHHMMSS (UTC)."""
    return value.strftime("%Y%m%d%H%M%S")


def _url_for_query(query: str, start: datetime, end: datetime) -> str:
    """GDELT DOC 2.0 timeline URL for one query over a date range (raw daily volume counts).

    mode=timelinevolraw returns raw article counts per time bucket; timelinesmooth=0 keeps it unsmoothed
    (no look-ahead from a centered moving average). format=json for deterministic parsing."""
    params = urllib.parse.urlencode(
        {
            "query": query,
            "mode": "timelinevolraw",
            "format": "json",
            "timelinesmooth": "0",
            "startdatetime": _gdelt_dt(start),
            "enddatetime": _gdelt_dt(end),
        }
    )
    return f"{_API_BASE}?{params}"


def _parse_date(raw: str) -> datetime | None:
    """Parse a GDELT timeline date stamp into midnight-UTC of the observation day.

    GDELT returns stamps like "20240601T000000Z" or "20240601000000". We take the leading YYYYMMDD and
    normalize to midnight UTC of that day (these are daily buckets)."""
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]), tzinfo=UTC)
    except ValueError:
        return None


def _parse_response(payload: dict) -> list[AltDataPoint]:
    """Parse a GDELT DOC 2.0 timelinevolraw response into AltDataPoints.

    PIT contract:
      ts           = midnight UTC of the recorded day
      available_at = ts + 1 day (the earliest a full day's count is realistically knowable)
      gap          = absent point, never zero
    The API returns {"timeline": [{"series": "...", "data": [{"date": "...", "value": N}, ...]}]}.
    Daily buckets with the same day are summed (defensive — should already be one point per day)."""
    timeline = payload.get("timeline") or []
    daily: dict[datetime, float] = {}
    for series in timeline:
        for item in series.get("data") or []:
            ts = _parse_date(item.get("date", ""))
            value = item.get("value")
            if ts is None or value is None:
                continue
            try:
                daily[ts] = daily.get(ts, 0.0) + float(value)
            except (TypeError, ValueError):
                continue
    out = [
        AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=v)
        for ts, v in daily.items()
    ]
    return sorted(out, key=lambda p: p.ts)


class GdeltCountsSource:
    """GDELT 2.0 daily NEWS-VOLUME count per topic as a named, point-in-time DataSource.

    Each observation answers: "how many news articles matching this topic did GDELT index on UTC day D?"
    COUNTS ONLY — no tone, no narrative, no LLM. The per-symbol query is resolved via TOPIC_MAP (exact),
    then a base-asset strip+fallback. An unknown symbol returns a None-valued SourceFeature — never crashes.

    PIT contract: available_at = ts + 1 day (conservative ≥1-day lag for a complete UTC day's count);
    a query for `as_of` returns the latest day whose available_at ≤ as_of — never look-ahead. Gaps are
    absent (value=None), never zero-fabricated (a GDELT outage is unknown coverage, not zero articles).

    Confidence is low — news-volume is an exploratory orthogonal attention feature that must earn its
    place via OOS. The Gate is the disposal layer.

    Offline testability: inject _fetcher(url)->dict; all HTTP is isolated behind that single callable, so
    tests are fully deterministic without a key, network, or monkeypatching.
    """

    name: str = "gdelt_news_volume"
    kind: SourceKind = "sentiment"
    metric: str = "gdelt_news_volume"
    prior: str = (
        "GDELT daily NEWS-VOLUME count (number of global articles mentioning a topic) is a cheap, free, "
        "LLM-free attention/coverage proxy. A surge in press coverage often coincides with or slightly "
        "leads a narrative-driven move; this is the raw COUNTS axis only (tone/narrative deliberately "
        "closed). available_at = obs day + 1 (conservative ≥1-day lag for a complete UTC day). Gaps are "
        "None (not 0) — a GDELT outage is unknown coverage, not zero articles. Low-confidence until "
        "validated out-of-sample — the Gate is the disposal layer."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.35  # low / exploratory — must earn its place via OOS
    lookback_days: int = 365  # trailing window of daily counts requested per call

    def __init__(
        self,
        *,
        metric: str = "gdelt_news_volume",
        lookback_days: int = 365,
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self.metric = metric
        self.lookback_days = lookback_days
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(
            url, headers={"User-Agent": "cosmu-engine/0.1 (contact.moncory@gmail.com)"}
        )
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_raw_series(self, symbol: str, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch raw daily news-volume AltDataPoints for `symbol` whose available_at ≤ as_of.

        A gap (no data for a day) is ABSENT from the returned list — never zero-fabricated.
        Returns [] if the symbol is unknown or the API fails (graceful degradation, never raises)."""
        query = _query_for_symbol(symbol)
        if query is None:
            return []
        # Request from (as_of - lookback) to (as_of - 1 day): the last full day knowable given the 1-day lag.
        end_day = as_of - _AVAILABILITY_LAG
        start_day = end_day - timedelta(days=self.lookback_days - 1)
        url = _url_for_query(query, start_day, end_day + timedelta(days=1))
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash the gate pass
            return []
        raw = _parse_response(payload if isinstance(payload, dict) else {})
        pts = [p for p in raw if p.available_at <= as_of]  # strict point-in-time
        return pts[-limit:]

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest daily news-volume count for `scope` whose available_at ≤ as_of (point-in-time, no look-ahead).

        Returns a None-valued SourceFeature if the symbol is unknown, the API is unreachable, or nothing
        is knowable yet — NEVER raises, NEVER fabricates a 0 for a gap."""
        raw = self.fetch_raw_series(scope, as_of, limit=limit)
        latest: AltDataPoint | None = None
        for p in raw:
            if p.available_at <= as_of:
                latest = p  # ascending order → the last valid one is the latest knowable

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
    "TOPIC_MAP",
    "TRANSFORM_VERSION",
    "GdeltCountsSource",
    "_parse_response",
    "_query_for_symbol",
]
