# Regression: a deep on-disk bar cache must NEVER shrink when fetch_bars(limit > cached) triggers a
# network refetch. A single Binance/Kraken/Bybit page caps at ~1000 bars; before the fix a
# fetch_bars(limit=3000) against a 2000-bar cache OVERWROTE it down to the fetched 1000-bar tail. That
# was the corruption that truncated the shared deep perp cache during the edge-hunt campaign (a deep
# cache silently became a shallow window with no error). Offline + deterministic: the network seam is
# stubbed, so these tests never touch the wire.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cosmu.data.market import (
    Bar,
    BinanceSpotOHLCVProvider,
    BybitSpotOHLCVProvider,
    KrakenSpotOHLCVProvider,
)

_DAY_MS = 86_400_000


def _bars(n: int, *, start_day: int = 0) -> list[Bar]:
    """N ascending daily bars; price == day index so identity/ordering is checkable."""
    out: list[Bar] = []
    for i in range(n):
        day = start_day + i
        ts = datetime.fromtimestamp((day * _DAY_MS) / 1000, tz=UTC)
        p = Decimal(str(day))
        out.append(Bar(ts=ts, open=p, high=p, low=p, close=p, volume=p))
    return out


def _make(kind: str, cache_dir):
    return {
        "binance": BinanceSpotOHLCVProvider,
        "kraken": KrakenSpotOHLCVProvider,
        "bybit": BybitSpotOHLCVProvider,
    }[kind](cache_dir=cache_dir)


def _stub_fetch(provider, monkeypatch, bars: list[Bar]) -> None:
    """Point every network path of `provider` at a canned page (no wire)."""
    if isinstance(provider, BinanceSpotOHLCVProvider):
        monkeypatch.setattr(provider, "_fetch_with_ccxt", lambda *a, **k: list(bars))
        monkeypatch.setattr(provider, "_fetch_with_rest", lambda *a, **k: list(bars))
    else:  # Kraken / Bybit both funnel through _fetch_rest
        monkeypatch.setattr(provider, "_fetch_rest", lambda *a, **k: list(bars))


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_short_page_never_shrinks_deep_cache(kind, tmp_path, monkeypatch):
    provider = _make(kind, tmp_path)
    deep = _bars(2000)  # the deep cache (e.g. start 2020-12)
    provider._write_cache("BTCUSDT", "1d", deep)
    assert len(provider._read_cache("BTCUSDT", "1d")) == 2000

    # A single network page caps at 1000 — the most-recent tail of the deep history.
    _stub_fetch(provider, monkeypatch, deep[-1000:])

    result = provider.fetch_bars("BTCUSDT", "1d", limit=3000)

    # The cache must NOT have been truncated to the fetched 1000-bar tail.
    assert len(provider._read_cache("BTCUSDT", "1d")) == 2000
    # The call serves the full deep window (capped at what exists) with the oldest bar preserved.
    assert len(result) == 2000
    assert result[0].ts == deep[0].ts
    assert result[-1].ts == deep[-1].ts


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_fresh_page_extends_cache(kind, tmp_path, monkeypatch):
    provider = _make(kind, tmp_path)
    deep = _bars(2000)  # days 0..1999
    provider._write_cache("BTCUSDT", "1d", deep)

    # A page that overlaps the tail and adds 500 NEW bars beyond it (days 1500..2499).
    _stub_fetch(provider, monkeypatch, _bars(1000, start_day=1500))

    result = provider.fetch_bars("BTCUSDT", "1d", limit=3000)

    assert len(provider._read_cache("BTCUSDT", "1d")) == 2500  # grew, didn't replace
    assert len(result) == 2500
    assert result[0].ts == deep[0].ts  # oldest history kept
    assert result[-1].ts == _bars(1, start_day=2499)[0].ts  # newest extension present


@pytest.mark.parametrize("kind", ["binance", "kraken", "bybit"])
def test_empty_fetch_preserves_cache(kind, tmp_path, monkeypatch):
    provider = _make(kind, tmp_path)
    deep = _bars(2000)
    provider._write_cache("BTCUSDT", "1d", deep)

    _stub_fetch(provider, monkeypatch, [])  # network failure / empty response

    result = provider.fetch_bars("BTCUSDT", "1d", limit=3000)

    assert len(provider._read_cache("BTCUSDT", "1d")) == 2000  # never wiped to empty
    assert len(result) == 2000


def test_atomic_write_leaves_no_temp_files(tmp_path, monkeypatch):
    provider = BinanceSpotOHLCVProvider(cache_dir=tmp_path)
    provider._write_cache("BTCUSDT", "1d", _bars(2000))
    _stub_fetch(provider, monkeypatch, _bars(1000, start_day=2000))
    provider.fetch_bars("BTCUSDT", "1d", limit=3000)
    assert list(tmp_path.glob("*.tmp")) == []  # mkstemp temp is renamed away, never left behind
