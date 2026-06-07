"""CryptoPanic news-vote DataSource — offline, deterministic, no network, no key.

Tests prove:
1. PIT contract: available_at == as_of (vote snapshot is knowable only at observation time).
2. No look-ahead: posts published AFTER as_of are excluded.
3. No fabrication: a gap (no posts in window) returns None, never a synthetic zero.
4. Window filter: only posts within (as_of - 24h, as_of] are summed.
5. Coin filter: votes for other coins are excluded from the target coin's count.
6. Key-gate: no api_key + not offline → [] (honest degradation).
7. DataSource protocol: both sources satisfy the registry DataSource protocol.
8. Revision safety: a later re-fetch (with different counts) produces a different snapshot
   but available_at is always the current fetch time (no rewriting of earlier history).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.cryptopanic import (
    TRANSFORM_VERSION,
    CryptoPanicBearishVotesSource,
    CryptoPanicBullishVotesSource,
    CryptoPanicProvider,
    _aggregate_votes,
    _coin_from_symbol,
    _has_posts_in_window,
    _parse_published_at,
)
from cosmu.data.sources.registry import DataSource

# Shared as_of: 2024-01-01 16:00 UTC. Posts at 10:00 and 14:00 are in the 24h window;
# the post at 2023-12-31 00:00 is outside the window.
_AS_OF = datetime(2024, 1, 1, 16, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _offline_provider() -> CryptoPanicProvider:
    """Provider using the bundled offline fixture — no key, no network."""
    return CryptoPanicProvider(offline=True)


def _no_key_provider() -> CryptoPanicProvider:
    """Provider with no key and not offline → should return [] (honest degradation)."""
    return CryptoPanicProvider(offline=False, api_key="")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_parse_published_at_iso():
    dt = _parse_published_at("2024-01-01T10:00:00Z")
    assert dt is not None
    assert dt == datetime(2024, 1, 1, 10, tzinfo=UTC)


def test_parse_published_at_none_on_empty():
    assert _parse_published_at("") is None
    assert _parse_published_at(None) is None  # type: ignore[arg-type]


def test_coin_from_symbol_strips_usdt():
    assert _coin_from_symbol("BTCUSDT") == "BTC"
    assert _coin_from_symbol("ETHUSDT") == "ETH"
    assert _coin_from_symbol("SOLUSDT") == "SOL"


def test_coin_from_symbol_fallback():
    # Unknown pair: return as-is in uppercase
    assert _coin_from_symbol("XYZ") == "XYZ"


def test_aggregate_votes_window_filter():
    """Posts outside the 24h window must NOT be counted."""
    posts = _offline_provider().fetch_posts("BTC")
    bullish, bearish = _aggregate_votes(posts, "BTC", _AS_OF, 24)
    # Fixture: BTC posts at 10:00 (+42 bull, +3 bear) and 14:00 (+18 bull, +12 bear)
    # Post at 2023-12-31 00:00 is outside 24h window → excluded
    assert bullish == 42 + 18  # 60
    assert bearish == 3 + 12   # 15


def test_aggregate_votes_coin_filter():
    """Votes for ETH must not appear in BTC aggregation."""
    posts = _offline_provider().fetch_posts("BTC")
    # 24h window from 2024-01-01T16:00Z covers BTC posts at 10:00 and 14:00 (id=1001 and id=1003).
    # The ETH post (id=1002, positive=8, negative=20) MUST NOT appear in BTC counts.
    bullish, bearish = _aggregate_votes(posts, "BTC", _AS_OF, 24)
    assert bullish == 42 + 18  # BTC-only; ETH's 8 is excluded
    assert bearish == 3 + 12   # BTC-only; ETH's 20 is excluded


def test_has_posts_in_window_true_and_false():
    posts = _offline_provider().fetch_posts("BTC")
    assert _has_posts_in_window(posts, "BTC", _AS_OF, 24) is True
    # Before any BTC post in window — as_of before the first BTC post
    early_as_of = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    assert _has_posts_in_window(posts, "BTC", early_as_of, 24) is False


def test_has_posts_in_window_no_lookahead():
    """Posts published AFTER as_of must never be included."""
    posts = _offline_provider().fetch_posts("BTC")
    # as_of is before all 2024-01-01 posts
    as_of_early = datetime(2024, 1, 1, 9, 59, tzinfo=UTC)
    assert _has_posts_in_window(posts, "BTC", as_of_early, 24) is False


# ---------------------------------------------------------------------------
# DataSource: bullish votes
# ---------------------------------------------------------------------------


def test_bullish_votes_pit_no_lookahead():
    """available_at == as_of; posts after as_of are never included."""
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.value == 60.0  # 42+18
    assert f.available_at == _AS_OF  # snapshot time IS the available_at
    assert f.as_of == _AS_OF


def test_bullish_votes_gap_returns_none_not_zero():
    """No BTC posts in window before the first fixture post → None (not 0)."""
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    as_of_before = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    f = src.query("BTCUSDT", as_of_before)
    assert f.value is None
    assert f.available_at is None


def test_bullish_votes_correct_coin_isolation():
    """ETH votes must not bleed into BTCUSDT query."""
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    # ETH post positive=8 must not be counted
    assert f.value == 60.0  # only BTC posts


def test_bullish_votes_low_confidence_flag():
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.low_confidence is True
    assert f.confidence < 0.5


def test_bullish_votes_transform_version():
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.transform_version == TRANSFORM_VERSION


def test_bullish_votes_scope_passed_through():
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.scope == "BTCUSDT"


# ---------------------------------------------------------------------------
# DataSource: bearish votes
# ---------------------------------------------------------------------------


def test_bearish_votes_pit_no_lookahead():
    src = CryptoPanicBearishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.value == 15.0  # 3+12
    assert f.available_at == _AS_OF
    assert f.as_of == _AS_OF


def test_bearish_votes_gap_returns_none():
    src = CryptoPanicBearishVotesSource(provider=_offline_provider())
    as_of_before = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    f = src.query("BTCUSDT", as_of_before)
    assert f.value is None
    assert f.available_at is None


def test_bearish_votes_low_confidence():
    src = CryptoPanicBearishVotesSource(provider=_offline_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.low_confidence is True


# ---------------------------------------------------------------------------
# Key-gate: honest degradation
# ---------------------------------------------------------------------------


def test_no_key_returns_empty_no_fabrication():
    """A provider with no key and not offline must return [] — never fabricate data."""
    provider = _no_key_provider()
    posts = provider.fetch_posts("BTC")
    assert posts == []


def test_no_key_bullish_source_returns_none():
    """With no posts (key-gated), query must return None, not 0 or a fabricated value."""
    src = CryptoPanicBullishVotesSource(provider=_no_key_provider())
    f = src.query("BTCUSDT", _AS_OF)
    assert f.value is None
    assert f.available_at is None


# ---------------------------------------------------------------------------
# DataSource protocol conformance
# ---------------------------------------------------------------------------


def test_both_sources_satisfy_datasource_protocol():
    from cosmu.data.sources.registry import DataSourceRegistry

    bull = CryptoPanicBullishVotesSource(provider=_offline_provider())
    bear = CryptoPanicBearishVotesSource(provider=_offline_provider())
    assert isinstance(bull, DataSource)
    assert isinstance(bear, DataSource)
    reg = DataSourceRegistry()
    reg.register(bull)
    reg.register(bear)
    assert "cryptopanic_bullish_votes" in reg.names()
    assert "cryptopanic_bearish_votes" in reg.names()


# ---------------------------------------------------------------------------
# Revision safety: later snapshot does not rewrite earlier available_at
# ---------------------------------------------------------------------------


def test_revision_safety_available_at_is_query_time():
    """Two queries at different times produce different available_at stamps — history is immutable."""
    src = CryptoPanicBullishVotesSource(provider=_offline_provider())
    t1 = datetime(2024, 1, 1, 16, 0, tzinfo=UTC)
    t2 = datetime(2024, 1, 1, 20, 0, tzinfo=UTC)
    f1 = src.query("BTCUSDT", t1)
    f2 = src.query("BTCUSDT", t2)
    # Both return data (t2 window still contains the same BTC posts)
    assert f1.available_at == t1
    assert f2.available_at == t2
    assert f1.available_at != f2.available_at  # different snapshots, different stamps
