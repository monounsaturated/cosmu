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


class StooqDailyBarsProvider:
    """Free daily equity bars via Stooq CSV (no key). Known limit: Stooq lists only CURRENTLY-traded
    symbols — it is SURVIVORSHIP-BIASED (delisted names are absent). Declared, not hidden: this proves
    signal *presence* cross-asset, not deployable capacity. Norgate replaces it at the live phase."""

    survivorship_complete = False  # free bars have no delisted names — see class docstring

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/stooq") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        cached = self._read_cache(symbol)
        if cached:
            return cached[-limit:]
        bars = self._fetch_csv(symbol)
        if bars:
            self._write_cache(symbol, bars)
        return bars[-limit:]

    def _fetch_csv(self, symbol: str) -> list[Bar]:
        # Stooq US tickers are suffixed ".us" (e.g. spy.us); pass-through if already qualified.
        s = symbol.lower() if "." in symbol else f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/d/l/?{urllib.parse.urlencode({'s': s, 'i': 'd'})}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            text = resp.read().decode("utf-8")
        out: list[Bar] = []
        for line in text.splitlines()[1:]:  # skip CSV header
            cols = line.split(",")
            if len(cols) < 6 or cols[1] in ("", "null"):
                continue
            out.append(
                Bar(
                    ts=datetime.fromisoformat(cols[0]).replace(tzinfo=UTC),
                    open=Decimal(cols[1]), high=Decimal(cols[2]), low=Decimal(cols[3]),
                    close=Decimal(cols[4]), volume=Decimal(cols[5] or "0"),
                )
            )
        return out

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.replace('/', '_')}_1d.json"

    def _read_cache(self, symbol: str) -> list[Bar]:
        path = self._cache_path(symbol)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, bars: list[Bar]) -> None:
        rows = [
            {"ts": int(b.ts.timestamp() * 1000), "open": str(b.open), "high": str(b.high),
             "low": str(b.low), "close": str(b.close), "volume": str(b.volume)}
            for b in bars
        ]
        self._cache_path(symbol).write_text(json.dumps(rows, separators=(",", ":")))


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
