# Kraken Futures DataAdapter: protocol conformance + point-in-time honesty. All tests use offline fixtures.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.kraken_futures import KrakenFuturesDataAdapter
from cosmu.core.interfaces import DataAdapter, ProductType

T0 = datetime(2025, 1, 1, tzinfo=UTC)
T0_MS = int(T0.timestamp() * 1000)


class FixtureKFProvider:
    """Canned Kraken Futures v3 candle response: {candles: [{time, open, high, low, close, volume}, ...]}"""

    def __init__(self, candles: list[dict]) -> None:
        self._candles = candles

    def fetch_candles(self, symbol: str, resolution: str, *, from_ms: int, to_ms: int) -> list[dict]:
        return self._candles


def _make_candles(n: int = 3) -> list[dict]:
    return [
        {
            "time":   T0_MS + i * 86_400_000,
            "open":   96000.0,
            "high":   97000.0,
            "low":    95000.0,
            "close":  96500.0,
            "volume": 1500.0,
        }
        for i in range(n)
    ]


def test_kraken_futures_adapter_conforms() -> None:
    assert isinstance(KrakenFuturesDataAdapter(["PF_XBTUSD"]), DataAdapter)


def test_universe_returns_perps() -> None:
    adapter = KrakenFuturesDataAdapter(
        ["PF_XBTUSD", "PF_ETHUSD"], market_provider=FixtureKFProvider([])
    )
    instruments = adapter.universe(T0)
    assert all(i.product_type == ProductType.PERP for i in instruments)
    assert all(i.venue == "kraken_futures" for i in instruments)
    assert {i.symbol for i in instruments} == {"PF_XBTUSD", "PF_ETHUSD"}


def test_bars_parsed_from_canned_response() -> None:
    candles = _make_candles(3)
    adapter = KrakenFuturesDataAdapter(["PF_XBTUSD"], market_provider=FixtureKFProvider(candles))
    bars = adapter.bars("crypto:kraken_futures:PF_XBTUSD", T0, T0 + timedelta(days=10), "1d")
    assert len(bars) == 3
    assert bars[0].open == Decimal("96000.0")
    assert bars[0].close == Decimal("96500.0")
    assert bars[0].volume == Decimal("1500.0")


def test_bars_are_point_in_time() -> None:
    """A daily bar is available only after it closes (ts + 1 day)."""
    candles = _make_candles(2)
    adapter = KrakenFuturesDataAdapter(["PF_XBTUSD"], market_provider=FixtureKFProvider(candles))
    bars = adapter.bars("crypto:kraken_futures:PF_XBTUSD", T0, T0 + timedelta(days=5), "1d")
    assert bars[0].available_at == bars[0].ts + timedelta(days=1)
    assert all(b.available_at > b.ts for b in bars)


def test_bars_filtered_to_window() -> None:
    candles = _make_candles(5)  # T0 … T0+4d
    adapter = KrakenFuturesDataAdapter(["PF_XBTUSD"], market_provider=FixtureKFProvider(candles))
    bars = adapter.bars(
        "crypto:kraken_futures:PF_XBTUSD",
        T0 + timedelta(days=2), T0 + timedelta(days=3), "1d",
    )
    assert all(T0 + timedelta(days=2) <= b.ts <= T0 + timedelta(days=3) for b in bars)


def test_features_returns_empty() -> None:
    adapter = KrakenFuturesDataAdapter(["PF_XBTUSD"], market_provider=FixtureKFProvider([]))
    assert adapter.features("crypto:kraken_futures:PF_XBTUSD", T0) == []
