# Offline parse-step tests for the free market-data providers (Kraken / Bybit / Yahoo). Canned payloads,
# no network: assert correct OHLCV fields, ascending order, and point-in-time-honest bar timestamps.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.data.market import (
    YahooDailyBarsProvider,
    _bars_from_bybit,
    _bars_from_kraken,
    _bars_from_yahoo,
    _kraken_pair,
)


def test_kraken_parse_fields_and_ascending_order():
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": [
                [1672531200, "16500.0", "16800.0", "16400.0", "16700.0", "16600.0", "1234.5", 100],
                [1672617600, "16700.0", "17000.0", "16650.0", "16950.0", "16850.0", "2345.6", 200],
            ],
            "last": 1672617600,
        },
    }
    bars = _bars_from_kraken(payload)
    assert len(bars) == 2
    assert bars[0].ts == datetime(2023, 1, 1, tzinfo=UTC)
    assert bars[0].open == Decimal("16500.0")
    assert bars[0].high == Decimal("16800.0")
    assert bars[0].low == Decimal("16400.0")
    assert bars[0].close == Decimal("16700.0")
    assert bars[0].volume == Decimal("1234.5")  # column 6, not the vwap at column 5
    assert [b.ts for b in bars] == sorted(b.ts for b in bars)


def test_kraken_pair_maps_btc_usdt_to_xbtusd():
    assert _kraken_pair("BTCUSDT") == "XBTUSD"
    assert _kraken_pair("ETHUSD") == "ETHUSD"
    assert _kraken_pair("SOLUSDT") == "SOLUSD"


def test_bybit_parse_resorts_newest_first_to_ascending():
    payload = {
        "result": {
            "list": [
                ["1672617600000", "16700", "17000", "16650", "16950", "2345.6", "111"],  # newest first
                ["1672531200000", "16500", "16800", "16400", "16700", "1234.5", "222"],
            ]
        }
    }
    bars = _bars_from_bybit(payload)
    assert len(bars) == 2
    # re-sorted ascending so the contract matches every other provider
    assert bars[0].ts == datetime(2023, 1, 1, tzinfo=UTC)
    assert bars[1].ts == datetime(2023, 1, 2, tzinfo=UTC)
    assert bars[0].close == Decimal("16700")
    assert bars[0].volume == Decimal("1234.5")


def test_yahoo_parse_skips_gap_days_and_declares_survivorship():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1672531200, 1672617600, 1672704000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [380.0, None, 382.0],  # middle row is a Yahoo gap (holiday)
                                "high": [381.0, None, 383.0],
                                "low": [379.0, None, 381.5],
                                "close": [380.5, None, 382.5],
                                "volume": [1000000, None, 1100000],
                            }
                        ]
                    },
                }
            ]
        }
    }
    bars = _bars_from_yahoo(payload)
    assert len(bars) == 2  # the None gap day is skipped, never zero-filled
    assert bars[0].ts == datetime(2023, 1, 1, tzinfo=UTC)
    assert bars[1].ts == datetime(2023, 1, 3, tzinfo=UTC)
    assert bars[0].open == Decimal("380.0")
    # like Stooq, Yahoo is declared survivorship-incomplete (free bars have no delisted names)
    assert YahooDailyBarsProvider.survivorship_complete is False


def test_yahoo_empty_payload_is_safe():
    assert _bars_from_yahoo({"chart": {"result": []}}) == []
    assert _bars_from_yahoo({}) == []
