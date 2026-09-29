# Hyperliquid DataAdapter — offline, deterministic (no network). Proves: universe() yields hyperliquid USDC
# perps; bars() parses OHLCV; PIT honesty (available_at = the candle CLOSE time, never earlier than ts, with a
# ts+interval fallback); and the [start, end] window filter. Injected fixture provider — no live `/info` call.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.hyperliquid import HyperliquidDataAdapter
from cosmu.core.interfaces import AssetClass, ProductType


class _FakeHL:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetch_candles(self, coin: str, interval: str, *, start_ms: int, end_ms: int) -> list[dict]:
        return self._rows


def _candle(open_ms: int, close_ms: int | None, o, h, l, c, v) -> dict:  # noqa: E741
    row = {"t": open_ms, "o": str(o), "h": str(h), "l": str(l), "c": str(c), "v": str(v)}
    if close_ms is not None:
        row["T"] = close_ms
    return row


def test_universe_is_hyperliquid_usdc_perps() -> None:
    insts = HyperliquidDataAdapter(["BTC", "ETH"]).universe(datetime(2024, 1, 1, tzinfo=UTC))
    assert {i.symbol for i in insts} == {"BTC", "ETH"}
    assert all(i.venue == "hyperliquid" for i in insts)
    assert all(i.product_type == ProductType.PERP for i in insts)
    assert all(i.asset_class == AssetClass.CRYPTO for i in insts)
    assert all(i.quote_ccy == "USDC" for i in insts)


def test_bars_parse_ohlcv_and_pit_close_time() -> None:
    open_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    close_ms = int(datetime(2024, 1, 2, tzinfo=UTC).timestamp() * 1000)
    adapter = HyperliquidDataAdapter(["BTC"], market_provider=_FakeHL([_candle(open_ms, close_ms, 100, 110, 95, 105, 1234)]))
    bars = adapter.bars("crypto:hyperliquid:BTC", datetime(2023, 12, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC), "1d")
    assert len(bars) == 1
    b = bars[0]
    assert b.open == Decimal("100") and b.high == Decimal("110") and b.low == Decimal("95") and b.close == Decimal("105")
    assert b.volume == Decimal("1234")
    assert b.ts == datetime(2024, 1, 1, tzinfo=UTC)
    # PIT: a bar is observable only at its close — available_at is the candle close, strictly after ts.
    assert b.available_at == datetime(2024, 1, 2, tzinfo=UTC)
    assert b.available_at > b.ts


def test_bars_window_filter_and_avail_fallback() -> None:
    open_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
    adapter = HyperliquidDataAdapter(["ETH"], market_provider=_FakeHL([_candle(open_ms, None, 1, 1, 1, 1, 1)]))
    # Out-of-window → dropped.
    assert adapter.bars("crypto:hyperliquid:ETH", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC), "1h") == []
    # In-window, and with no close stamp the PIT fallback is ts + one interval.
    got = adapter.bars("crypto:hyperliquid:ETH", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), "1h")
    assert len(got) == 1
    assert got[0].available_at == got[0].ts + timedelta(hours=1)
