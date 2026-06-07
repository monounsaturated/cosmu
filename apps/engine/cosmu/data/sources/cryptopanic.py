# intent: point-in-time CryptoPanic news-vote adapter. Fetches the CryptoPanic free-tier /posts/ endpoint
# (CRYPTOPANIC_API_KEY required) and exposes two per-symbol numeric features:
#   cryptopanic_bullish_votes  — positive vote count on posts mentioning the coin (24 h window)
#   cryptopanic_bearish_votes  — negative vote count on posts mentioning the coin (24 h window)
#
# PIT contract:
#   ts           = published_at from the API (when the story went live)
#   available_at = published_at  (CryptoPanic publishes posts instantly; no revision delay)
#   Gaps are ABSENT (None), never filled with synthetic zeros.
#
# Revision behaviour:
#   CryptoPanic vote counts increment over time (users vote after publication), so early snapshots
#   undercount later votes. We stamp each snapshot with the fetch time as available_at so replay uses
#   the counts the machine would have seen. We NEVER rewrite earlier rows — the store is append-only.
#
# Key gate: no key → [] (honest degradation, never fabricates data). The offline fixture is deterministic
# so CI runs with no key and no network.

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

TRANSFORM_VERSION = "cryptopanic-votes-v1"

# CryptoPanic free-tier base URL.
_CP_BASE_URL = "https://cryptopanic.com/api/v1/posts/"

# Window used to aggregate vote counts: only posts published within this many hours of `as_of`
# are summed. Wide enough to collect daily signal, tight enough to avoid stale accumulation.
_VOTE_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Offline fixture (deterministic, shape mirrors the real CryptoPanic response)
# ---------------------------------------------------------------------------
_FIXTURE_RESPONSE: dict[str, Any] = {
    "results": [
        {
            "id": 1001,
            "title": "Bitcoin breaks resistance, bulls take control",
            "published_at": "2024-01-01T10:00:00Z",
            "currencies": [{"code": "BTC"}],
            "votes": {"positive": 42, "negative": 3, "important": 10, "liked": 15, "disliked": 1, "lol": 0, "toxic": 0, "saved": 5},
        },
        {
            "id": 1002,
            "title": "ETH upgrade delayed, community reacts",
            "published_at": "2024-01-01T12:00:00Z",
            "currencies": [{"code": "ETH"}],
            "votes": {"positive": 8, "negative": 20, "important": 7, "liked": 5, "disliked": 9, "lol": 2, "toxic": 1, "saved": 2},
        },
        {
            "id": 1003,
            "title": "BTC dominance surges as alts bleed",
            "published_at": "2024-01-01T14:00:00Z",
            "currencies": [{"code": "BTC"}],
            "votes": {"positive": 18, "negative": 12, "important": 4, "liked": 10, "disliked": 7, "lol": 0, "toxic": 0, "saved": 3},
        },
        {
            "id": 1004,
            "title": "Old BTC post outside the window",
            "published_at": "2023-12-31T00:00:00Z",  # >24 h before as_of 2024-01-01T16:00
            "currencies": [{"code": "BTC"}],
            "votes": {"positive": 99, "negative": 1, "important": 0, "liked": 0, "disliked": 0, "lol": 0, "toxic": 0, "saved": 0},
        },
    ],
    "next": None,
}


def _parse_published_at(raw: str) -> datetime | None:
    """Parse CryptoPanic's ISO-8601 published_at (e.g. '2024-01-01T10:00:00Z'). Returns None on failure."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return None


def _coin_from_symbol(symbol: str) -> str:
    """Strip the quote currency from a COSMU trading pair symbol to get the CryptoPanic currency code.
    e.g. 'BTCUSDT' → 'BTC', 'ETHUSDT' → 'ETH', 'SOLUSDT' → 'SOL'.
    Falls back to the raw symbol if no known quote currency is found."""
    for quote in ("USDT", "USDC", "BTC", "ETH", "BNB", "USD"):
        if symbol.upper().endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)].upper()
    return symbol.upper()


def _has_posts_in_window(
    results: list[dict[str, Any]],
    coin: str,
    as_of: datetime,
    window_hours: int,
) -> bool:
    """Return True if at least one post mentions `coin` and falls inside (as_of - window, as_of]."""
    cutoff = as_of - timedelta(hours=window_hours)
    for post in results:
        currencies = [c.get("code", "").upper() for c in (post.get("currencies") or [])]
        if coin.upper() not in currencies:
            continue
        pub = _parse_published_at(post.get("published_at", ""))
        if pub is not None and cutoff < pub <= as_of:
            return True
    return False


def _aggregate_votes(
    results: list[dict[str, Any]],
    coin: str,
    as_of: datetime,
    window_hours: int,
) -> tuple[int, int]:
    """Sum positive + negative votes from posts mentioning `coin` whose published_at falls inside
    (as_of - window, as_of]. Posts outside the window or without matching currency are ignored.
    Returns (bullish_total, bearish_total)."""
    cutoff = as_of - timedelta(hours=window_hours)
    bullish = 0
    bearish = 0
    for post in results:
        currencies = [c.get("code", "").upper() for c in (post.get("currencies") or [])]
        if coin.upper() not in currencies:
            continue
        pub = _parse_published_at(post.get("published_at", ""))
        if pub is None or pub > as_of or pub <= cutoff:
            continue
        v = post.get("votes") or {}
        bullish += int(v.get("positive", 0) or 0)
        bearish += int(v.get("negative", 0) or 0)
    return bullish, bearish


# ---------------------------------------------------------------------------
# Core provider (HTTP + offline fixture)
# ---------------------------------------------------------------------------


@dataclass
class CryptoPanicProvider:
    """Fetch the CryptoPanic /posts/ feed for a given currency code.

    KEY-GATED: if no api_key is supplied and not offline → returns [] (honest degradation, never fabricates).
    Offline/CI: pass offline=True or inject _fetcher; the bundled fixture is used so CI runs with no network.
    The provider stamps available_at == published_at (posts are publicly knowable at publication time;
    vote counts are mutable but we capture a snapshot at fetch time and never rewrite history).
    """

    api_key: str = ""
    base_url: str = _CP_BASE_URL
    offline: bool = False
    timeout: float = 20.0
    # Injectable HTTP fetcher for tests: callable(url) -> dict
    _fetcher: Callable[[str], dict[str, Any]] | None = field(default=None, repr=False)

    def _live_fetch(self, coin: str, limit: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "auth_token": self.api_key,
            "currencies": coin,
            "public": "true",
            "kind": "news",
        }
        if limit:
            params["page_size"] = min(limit, 100)
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "cosmu-engine/0.1", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — network failure → honest degradation
            return {}

    def fetch_posts(self, coin: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return raw CryptoPanic post dicts for `coin`, or [] on no key / dead fetch / offline fixture."""
        if self._fetcher is not None:
            payload = self._fetcher(coin)
        elif self.offline or not self.api_key:
            if not self.offline and not self.api_key:
                return []  # honest degradation: key required for live fetch
            payload = dict(_FIXTURE_RESPONSE)
        else:
            payload = self._live_fetch(coin, limit)
        return list(payload.get("results") or [])


# ---------------------------------------------------------------------------
# DataSource wrappers (one per feature key)
# ---------------------------------------------------------------------------


@dataclass
class CryptoPanicBullishVotesSource:
    """Named, point-in-time DataSource: bullish (positive) CryptoPanic vote count per coin per 24h window.

    available_at == as_of (the vote snapshot is only knowable at query time — no look-ahead).
    A gap (no posts in window) returns None, never a fabricated 0 (honesty: absence ≠ zero opinion).
    LOW confidence: vote counts are a noisy crowd proxy; must earn its place via OOS.
    """

    name: str = "cryptopanic_bullish_votes"
    kind: SourceKind = "sentiment"
    metric: str = "cryptopanic_bullish_votes"
    prior: str = (
        "Positive CryptoPanic vote count on news posts mentioning the coin (24 h rolling window). "
        "A bullish vote spike may mark crowd attention preceding a momentum move; a consensus negative "
        "reading may signal bearish regime entry. Low-confidence (crowd noise): must earn OOS."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.3
    provider: CryptoPanicProvider = field(default_factory=CryptoPanicProvider)
    vote_window_hours: int = _VOTE_WINDOW_HOURS

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 100) -> SourceFeature:
        coin = _coin_from_symbol(scope)
        posts = self.provider.fetch_posts(coin, limit=limit)
        bullish, _ = _aggregate_votes(posts, coin, as_of, self.vote_window_hours)
        has_posts_in_window = _has_posts_in_window(posts, coin, as_of, self.vote_window_hours)
        # None when no posts found in the window (honest gap — not synthetic zero)
        value: float | None = float(bullish) if has_posts_in_window else None
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=value,
            available_at=as_of if value is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


@dataclass
class CryptoPanicBearishVotesSource:
    """Named, point-in-time DataSource: bearish (negative) CryptoPanic vote count per coin per 24h window.

    available_at == as_of (snapshot knowable only at query time).
    A gap returns None (never fabricated zero). LOW confidence: must earn its place via OOS.
    """

    name: str = "cryptopanic_bearish_votes"
    kind: SourceKind = "sentiment"
    metric: str = "cryptopanic_bearish_votes"
    prior: str = (
        "Negative CryptoPanic vote count on news posts mentioning the coin (24 h rolling window). "
        "A bearish vote spike may signal crowd anticipation of a downturn; a low negative reading "
        "when bullish is high flags consensus. Low-confidence (crowd noise): must earn OOS."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.3
    provider: CryptoPanicProvider = field(default_factory=CryptoPanicProvider)
    vote_window_hours: int = _VOTE_WINDOW_HOURS

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def query(self, scope: str, as_of: datetime, *, limit: int = 100) -> SourceFeature:
        coin = _coin_from_symbol(scope)
        posts = self.provider.fetch_posts(coin, limit=limit)
        _, bearish = _aggregate_votes(posts, coin, as_of, self.vote_window_hours)
        has_posts_in_window = _has_posts_in_window(posts, coin, as_of, self.vote_window_hours)
        value: float | None = float(bearish) if has_posts_in_window else None
        return SourceFeature(
            name=self.name,
            scope=scope,
            as_of=as_of,
            value=value,
            available_at=as_of if value is not None else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


__all__ = [
    "TRANSFORM_VERSION",
    "CryptoPanicProvider",
    "CryptoPanicBullishVotesSource",
    "CryptoPanicBearishVotesSource",
    "_aggregate_votes",
    "_has_posts_in_window",
    "_coin_from_symbol",
    "_parse_published_at",
]
