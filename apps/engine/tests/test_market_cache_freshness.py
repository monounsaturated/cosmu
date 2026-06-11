# Regression: the executor-freshness trap (PRE-LIVE gate, BACKLOG 2026-06-10). Before the fix,
# BinanceSpotOHLCVProvider.fetch_bars served a covering cache with NO freshness check (a deep cache froze the
# executor's view forever on a persistent filesystem), the exchange's in-progress candle was cached as if it
# were a final close (the 22:10 cron snapshotting the live daily candle), and _merge_bars kept the OLD row on a
# ts collision so that poisoned snapshot could never be repaired. These tests pin the fixed contract for all
# three crypto providers: closed candles only, stale-covering caches refetch, fetched rows repair cached rows,
# and offline behaviour still degrades to the cache (never raises where the old code served silently).
# Offline + deterministic: the network seam is stubbed and the clock is injected.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.data.market import (
    Bar,
    BinanceSpotOHLCVProvider,
    BybitSpotOHLCVProvider,
    KrakenSpotOHLCVProvider,
    _cache_is_fresh,
    _drop_unclosed,
)

_H = timedelta(hours=1)
# A fixed "wall clock" exactly on a daily boundary keeps the closed-bar arithmetic legible: with now at
# day D 00:00, the latest CLOSED daily candle opened at D-1 00:00 and the in-progress one opens at D 00:00.
_NOW = datetime(2026, 6, 11, 0, 0, tzinfo=UTC)


def _bar(ts: datetime, price: str) -> Bar:
    p = Decimal(price)
    return Bar(ts=ts, open=p, high=p, low=p, close=p, volume=p)


def _daily(n: int, *, end: datetime, price: str = "100") -> list[Bar]:
    """N ascending CLOSED daily bars, the newest opening at `end`."""
    return [_bar(end - timedelta(days=n - 1 - i), price) for i in range(n)]


def _make(kind: str, cache_dir, now: datetime):
    cls = {
        "binance": BinanceSpotOHLCVProvider,
        "kraken": KrakenSpotOHLCVProvider,
        "bybit": BybitSpotOHLCVProvider,
    }[kind]
    return cls(cache_dir=cache_dir, now_fn=lambda: now)


def _stub_fetch(provider, monkeypatch, bars: list[Bar] | Exception) -> dict[str, int]:
    """Point the provider's network seam at a canned page (or a raised error) and count the hits — the
    degrade-to-cache path swallows exceptions by design, so 'network not touched' must be asserted by count."""
    calls = {"n": 0}

    def _result(*_a, **_k):
        calls["n"] += 1
        if isinstance(bars, Exception):
            raise bars
        return list(bars)

    if isinstance(provider, BinanceSpotOHLCVProvider):
        monkeypatch.setattr(provider, "_fetch_with_ccxt", lambda *a, **k: [])
        monkeypatch.setattr(provider, "_fetch_with_rest", _result)
    else:
        monkeypatch.setattr(provider, "_fetch_rest", _result)
    return calls


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_unclosed_last_candle_never_cached_or_served(kind, tmp_path, monkeypatch):
    """The exchange returns the live in-progress candle as the last row — it must be dropped, not cached."""
    provider = _make(kind, tmp_path, _NOW)
    closed = _daily(5, end=_NOW - timedelta(days=1))
    in_progress = _bar(_NOW, "999")  # opens at now → closes at now+1d → NOT closed
    _stub_fetch(provider, monkeypatch, [*closed, in_progress])

    result = provider.fetch_bars("BTCUSDT", "1d", limit=5)

    assert [b.ts for b in result] == [b.ts for b in closed]
    assert all(b.ts < _NOW for b in provider._read_cache("BTCUSDT", "1d"))


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_stale_covering_cache_refetches(kind, tmp_path, monkeypatch):
    """A cache that covers the limit but whose newest bar is no longer the latest closed candle must refetch —
    the pre-fix behaviour served it forever (the frozen-executor trap)."""
    provider = _make(kind, tmp_path, _NOW)
    stale = _daily(10, end=_NOW - timedelta(days=4))  # newest closed 3 days ago
    provider._write_cache("BTCUSDT", "1d", stale)
    fresh_tail = _daily(4, end=_NOW - timedelta(days=1), price="200")
    _stub_fetch(provider, monkeypatch, fresh_tail)

    result = provider.fetch_bars("BTCUSDT", "1d", limit=5)

    assert result[-1].ts == _NOW - timedelta(days=1)  # the latest CLOSED candle is now served
    assert result[-1].close == Decimal("200")


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_fresh_covering_cache_skips_network(kind, tmp_path, monkeypatch):
    provider = _make(kind, tmp_path, _NOW + timedelta(minutes=7))  # just past the daily close
    fresh = _daily(10, end=_NOW - timedelta(days=1))  # newest = latest closed candle
    provider._write_cache("BTCUSDT", "1d", fresh)
    calls = _stub_fetch(provider, monkeypatch, [])

    result = provider.fetch_bars("BTCUSDT", "1d", limit=5)

    assert calls["n"] == 0  # a fresh covering cache serves without touching the network
    assert len(result) == 5
    assert result[-1].ts == _NOW - timedelta(days=1)


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_fetched_row_repairs_poisoned_cache_row(kind, tmp_path, monkeypatch):
    """A row cached while its candle was still forming (pre-fix 22:10 snapshot) is REPAIRED by the exchange's
    final values on the next fetch — the old existing-wins merge froze it forever."""
    provider = _make(kind, tmp_path, _NOW)
    poisoned_ts = _NOW - timedelta(days=1)
    history = _daily(5, end=_NOW - timedelta(days=2))
    provider._write_cache("BTCUSDT", "1d", [*history, _bar(poisoned_ts, "50")])  # mid-bar snapshot
    final = [_bar(poisoned_ts, "75")]  # the exchange's FINAL close for that candle
    _stub_fetch(provider, monkeypatch, final)

    # The poisoned row IS the latest closed candle by ts (the cache looks fresh), so force the fetch path
    # via a limit above the cache depth — exactly how a deeper-window request meets a poisoned tail in prod.
    result = provider.fetch_bars("BTCUSDT", "1d", limit=10)

    assert result[-1].ts == poisoned_ts
    assert result[-1].close == Decimal("75")  # repaired, not frozen at 50
    assert len(result) == 6  # union — nothing shrank


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_offline_stale_cache_still_serves(kind, tmp_path, monkeypatch):
    """Network down + stale covering cache → degrade to the cache (the pre-fix silent-serve), never raise."""
    provider = _make(kind, tmp_path, _NOW)
    stale = _daily(10, end=_NOW - timedelta(days=4))
    provider._write_cache("BTCUSDT", "1d", stale)
    _stub_fetch(provider, monkeypatch, OSError("network unreachable"))

    result = provider.fetch_bars("BTCUSDT", "1d", limit=5)

    assert len(result) == 5
    assert result[-1].ts == stale[-1].ts


def test_drop_unclosed_hourly_boundary():
    now = datetime(2026, 6, 11, 14, 30, tzinfo=UTC)
    bars = [
        _bar(datetime(2026, 6, 11, 12, 0, tzinfo=UTC), "1"),  # closed 13:00
        _bar(datetime(2026, 6, 11, 13, 0, tzinfo=UTC), "2"),  # closed 14:00
        _bar(datetime(2026, 6, 11, 14, 0, tzinfo=UTC), "3"),  # closes 15:00 → in-progress
    ]
    assert [b.close for b in _drop_unclosed(bars, "1h", now)] == [Decimal("1"), Decimal("2")]
    # Unknown timeframe: no period to judge by → unchanged (legacy behaviour).
    assert _drop_unclosed(bars, "3h", now) == bars


def test_cache_is_fresh_boundaries():
    now = datetime(2026, 6, 11, 14, 30, tzinfo=UTC)
    latest_closed = [_bar(datetime(2026, 6, 11, 13, 0, tzinfo=UTC), "1")]
    one_behind = [_bar(datetime(2026, 6, 11, 12, 0, tzinfo=UTC), "1")]
    assert _cache_is_fresh(latest_closed, "1h", now) is True
    assert _cache_is_fresh(one_behind, "1h", now) is False
    assert _cache_is_fresh([], "1h", now) is False
    assert _cache_is_fresh(one_behind, "3h", now) is True  # unknown timeframe → legacy serve
