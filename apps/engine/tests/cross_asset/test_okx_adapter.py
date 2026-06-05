# OKX DataAdapter: protocol conformance + point-in-time honesty. All tests use offline fixtures — no network.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.okx import OKXDataAdapter
from cosmu.core.interfaces import DataAdapter, ProductType

T0 = datetime(2025, 1, 1, tzinfo=UTC)
T0_MS = int(T0.timestamp() * 1000)


class FixtureOKXProvider:
    """Canned OKX v5 candle response: [[ts_ms, open, high, low, close, vol, ...], ...]"""

    def __init__(self, rows: list[list[str]]) -> None:
        self._rows = rows

    def fetch_candles(self, inst_id: str, bar: str, *, limit: int) -> list[list[str]]:
        return self._rows[:limit]


def _make_rows(n: int = 3) -> list[list[str]]:
    return [
        [
            str(T0_MS + i * 86_400_000),  # ts_ms
            "96000.0", "97000.0", "95000.0", "96500.0",  # open/high/low/close
            "12.5",    # vol (base)
            "1200000", # volCcy (quote)
            "1200000", # volCcyQuote
            "1",       # confirm (closed bar)
        ]
        for i in range(n)
    ]


def test_okx_adapter_conforms() -> None:
    assert isinstance(OKXDataAdapter(["BTC-USDT"]), DataAdapter)


def test_universe_returns_spot_and_swap() -> None:
    adapter = OKXDataAdapter(["BTC-USDT", "BTC-USDT-SWAP"], market_provider=FixtureOKXProvider([]))
    instruments = adapter.universe(T0)
    types = {i.symbol: i.product_type for i in instruments}
    assert types["BTC-USDT"] == ProductType.SPOT
    assert types["BTC-USDT-SWAP"] == ProductType.PERP
    assert all(i.venue == "okx" for i in instruments)


def test_bars_parsed_from_canned_response() -> None:
    rows = _make_rows(3)
    adapter = OKXDataAdapter(["BTC-USDT"], market_provider=FixtureOKXProvider(rows))
    end = T0 + timedelta(days=10)
    bars = adapter.bars("crypto:okx:BTC-USDT", T0, end, "1d")
    assert len(bars) == 3
    assert bars[0].open == Decimal("96000.0")
    assert bars[0].close == Decimal("96500.0")
    assert bars[0].volume == Decimal("12.5")


def test_bars_are_point_in_time() -> None:
    """A daily bar opened at T0 is only known at T0 + 1 day (close + interval)."""
    rows = _make_rows(2)
    adapter = OKXDataAdapter(["BTC-USDT"], market_provider=FixtureOKXProvider(rows))
    bars = adapter.bars("crypto:okx:BTC-USDT", T0, T0 + timedelta(days=5), "1d")
    assert bars[0].available_at == bars[0].ts + timedelta(days=1)
    assert all(b.available_at > b.ts for b in bars)


def test_bars_filtered_to_window() -> None:
    """Bars outside [start, end] are excluded."""
    rows = _make_rows(5)  # T0 … T0+4d
    adapter = OKXDataAdapter(["BTC-USDT"], market_provider=FixtureOKXProvider(rows))
    bars = adapter.bars("crypto:okx:BTC-USDT", T0 + timedelta(days=2), T0 + timedelta(days=3), "1d")
    assert all(T0 + timedelta(days=2) <= b.ts <= T0 + timedelta(days=3) for b in bars)


def test_features_returns_empty() -> None:
    adapter = OKXDataAdapter(["BTC-USDT"], market_provider=FixtureOKXProvider([]))
    assert adapter.features("crypto:okx:BTC-USDT", T0) == []
