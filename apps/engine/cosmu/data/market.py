# intent: fetch and cache Binance spot OHLCV bars; inputs: symbol/timeframe requests; outputs: ordered Bar records; invariants: secrets are never needed, cached bars remain exchange-sourced, and tests can inject a provider.

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class MarketDataProvider(Protocol):
    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        """Return ascending OHLCV bars for one venue symbol."""


class BinanceSpotOHLCVProvider:
    """Binance spot OHLCV provider with a ccxt path and a stdlib REST fallback."""

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/binance") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit:
            return cached[-limit:]

        bars = self._fetch_with_ccxt(symbol, timeframe, limit)
        if not bars:
            bars = self._fetch_with_rest(symbol, timeframe, limit)
        self._write_cache(symbol, timeframe, bars)
        return bars

    def _fetch_with_ccxt(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError:
            return []

        exchange = ccxt.binance({"enableRateLimit": True})
        market_symbol = _ccxt_symbol(symbol)
        rows = exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, limit=limit)
        return [_bar_from_ccxt(row) for row in rows]

    def _fetch_with_rest(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        query = urllib.parse.urlencode({"symbol": symbol, "interval": timeframe, "limit": limit})
        url = f"https://api.binance.com/api/v3/klines?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        return [_bar_from_binance(row) for row in rows]

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        rows = json.loads(path.read_text())
        return [_bar_from_json(row) for row in rows]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> None:
        path = self._cache_path(symbol, timeframe)
        rows = [
            {
                "ts": int(bar.ts.timestamp() * 1000),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume),
            }
            for bar in bars
        ]
        path.write_text(json.dumps(rows, separators=(",", ":")))


def _ccxt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT"
    return symbol


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _bar_from_ccxt(row: list[float | int]) -> Bar:
    ts, open_, high, low, close, volume = row[:6]
    return Bar(
        ts=datetime.fromtimestamp(float(ts) / 1000, tz=UTC),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _bar_from_binance(row: list[str | int]) -> Bar:
    return Bar(
        ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
        open=Decimal(str(row[1])),
        high=Decimal(str(row[2])),
        low=Decimal(str(row[3])),
        close=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
    )


def _bar_from_json(row: dict[str, str | int]) -> Bar:
    return Bar(
        ts=datetime.fromtimestamp(int(row["ts"]) / 1000, tz=UTC),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )
