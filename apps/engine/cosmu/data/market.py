# intent: fetch and cache Binance spot OHLCV bars; inputs: symbol/timeframe requests; outputs: ordered Bar records; invariants: secrets are never needed, cached bars remain exchange-sourced, and tests can inject a provider.

from __future__ import annotations

import json
import os
import ssl
import tempfile
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
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        # A single REST/ccxt page caps at 1000 bars; merge into (never overwrite) the cache so a
        # limit>cache fetch can only EXTEND a deep cache, never truncate it (see _write_cache).
        merged = self._write_cache(symbol, timeframe, bars)
        return merged[-limit:]

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

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge `bars` into the on-disk cache, deduped on ts — NEVER shrinks the cache.
        Re-reads the current file right before writing (and writes atomically), so a single 1000-bar
        page can't truncate a deep 2000-bar cache, and a concurrent writer's bars survive. Returns
        the merged, ascending bars so callers can serve the up-to-date window."""
        path = self._cache_path(symbol, timeframe)
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(path, json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


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
        _atomic_write_text(self._cache_path(symbol), json.dumps(_bars_to_rows(bars), separators=(",", ":")))


class KrakenSpotOHLCVProvider:
    """Free Kraken public OHLC (no key). Stdlib urllib + certifi SSL, disk-cached, separable parse fn.
    Kraken's REST returns at most ~720 bars per call; we cache and slice to the requested limit."""

    # Kraken takes the interval in MINUTES; map the common timeframe strings we use.
    _INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/kraken") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit:
            return cached[-limit:]
        bars = self._fetch_rest(symbol, timeframe)
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        return self._write_cache(symbol, timeframe, bars)[-limit:]

    def _fetch_rest(self, symbol: str, timeframe: str) -> list[Bar]:
        interval = self._INTERVAL_MINUTES.get(timeframe, 1440)
        pair = _kraken_pair(symbol)
        query = urllib.parse.urlencode({"pair": pair, "interval": interval})
        url = f"https://api.kraken.com/0/public/OHLC?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_kraken(payload)

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge into the cache (never shrinks; atomic write); returns the merged bars."""
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(self._cache_path(symbol, timeframe), json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


class BybitSpotOHLCVProvider:
    """Free Bybit v5 public spot kline (no key). Stdlib urllib + certifi SSL, disk-cached, separable parse fn.
    Bybit returns newest-first; the parse fn re-sorts ascending so the contract matches every other provider."""

    # Bybit v5 interval codes (minutes as strings, D/W/M for higher frames).
    _INTERVAL = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/bybit") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        cached = self._read_cache(symbol, timeframe)
        if len(cached) >= limit:
            return cached[-limit:]
        bars = self._fetch_rest(symbol, timeframe, limit)
        if not bars:
            return cached[-limit:]  # network empty → never shrink; serve what we have
        return self._write_cache(symbol, timeframe, bars)[-limit:]

    def _fetch_rest(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        interval = self._INTERVAL.get(timeframe, "D")
        query = urllib.parse.urlencode({"category": "spot", "symbol": symbol, "interval": interval, "limit": min(limit, 1000)})
        url = f"https://api.bybit.com/v5/market/kline?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_bybit(payload)

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = f"{symbol}_{timeframe}".replace("/", "")
        return self.cache_dir / f"{safe}.json"

    def _read_cache(self, symbol: str, timeframe: str) -> list[Bar]:
        path = self._cache_path(symbol, timeframe)
        if not path.exists():
            return []
        return [_bar_from_json(r) for r in json.loads(path.read_text())]

    def _write_cache(self, symbol: str, timeframe: str, bars: list[Bar]) -> list[Bar]:
        """Append-merge into the cache (never shrinks; atomic write); returns the merged bars."""
        merged = _merge_bars(self._read_cache(symbol, timeframe), bars)
        _atomic_write_text(self._cache_path(symbol, timeframe), json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged


class YahooDailyBarsProvider:
    """Free daily equity/ETF bars via the Yahoo Finance chart API (no key). Like Stooq it lists only
    CURRENTLY-traded symbols, so it is SURVIVORSHIP-BIASED (delisted names absent) — declared, not hidden:
    it proves cross-asset signal PRESENCE, not deployable capacity. Norgate replaces it at the live phase."""

    survivorship_complete = False  # free bars have no delisted names — see class docstring

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/yahoo") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        cached = self._read_cache(symbol)
        if cached:
            return cached[-limit:]
        bars = self._fetch_chart(symbol)
        if bars:
            self._write_cache(symbol, bars)
        return bars[-limit:]

    def _fetch_chart(self, symbol: str) -> list[Bar]:
        # Use an EXPLICIT epoch window (period1/period2), NOT range=max: Yahoo SILENTLY downgrades
        # range=max to MONTHLY bars (e.g. AAPL → ~168 month-start points) despite interval=1d, which
        # corrupts every "daily" backtest. A wide explicit window forces TRUE daily granularity. A real
        # browser User-Agent is also more reliable than a custom one.
        period2 = int(datetime.now(UTC).timestamp()) + 86_400  # now + 1d buffer
        query = urllib.parse.urlencode({"period1": 0, "period2": period2, "interval": "1d"})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _bars_from_yahoo(payload)

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.replace('/', '_')}_1d.json"

    def _read_cache(self, symbol: str) -> list[Bar]:
        path = self._cache_path(symbol)
        if not path.exists():
            return []
        bars = [_bar_from_json(r) for r in json.loads(path.read_text())]
        if bars and not _is_daily_spaced(bars):
            # poisoned cache: MONTHLY bars from the old `range=max` downgrade. Drop it so fetch_bars
            # re-fetches true daily history (the file is overwritten on the next successful fetch).
            return []
        return bars

    def _write_cache(self, symbol: str, bars: list[Bar]) -> None:
        _atomic_write_text(self._cache_path(symbol), json.dumps(_bars_to_rows(bars), separators=(",", ":")))


def _is_daily_spaced(bars: list[Bar]) -> bool:
    """True DAILY bars have consecutive-trading-day gaps (1-4 calendar days incl. weekends/holidays);
    MONTHLY bars (from the old Yahoo `range=max` downgrade) have ~28-31 day gaps. Median-gap test —
    used to detect + invalidate poisoned daily caches."""
    if len(bars) < 5:
        return True
    gaps = sorted((bars[i].ts - bars[i - 1].ts).days for i in range(1, len(bars)))
    return gaps[len(gaps) // 2] <= 7


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


def _merge_bars(existing: list[Bar], fetched: list[Bar]) -> list[Bar]:
    """Union two bar lists deduped on ts, ascending. `existing` wins on a ts collision (a closed bar is
    immutable, so the on-disk value is authoritative and merging stays idempotent). This is the core
    never-shrink invariant: merging a short fetched page with a deep cache can only ADD bars."""
    merged: dict[datetime, Bar] = {b.ts: b for b in fetched}
    merged.update({b.ts: b for b in existing})
    return sorted(merged.values(), key=lambda b: b.ts)


def _bars_to_rows(bars: list[Bar]) -> list[dict[str, int | str]]:
    """Serialize Bars to the on-disk cache row shape (ts in ms; OHLCV as strings to preserve Decimals)."""
    return [
        {"ts": int(b.ts.timestamp() * 1000), "open": str(b.open), "high": str(b.high),
         "low": str(b.low), "close": str(b.close), "volume": str(b.volume)}
        for b in bars
    ]


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (unique temp file in the same dir + os.replace) so a concurrent
    reader never observes a half-written/truncated cache — the torn-write race that let parallel harness
    runs across worktrees corrupt the shared bar cache."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def _kraken_pair(symbol: str) -> str:
    """Map our exchange symbol (BTCUSDT) to Kraken's pair convention (XBTUSD). USDT pairs map to USD
    spot since Kraken's deepest fiat books are USD; pass-through anything already Kraken-shaped."""
    s = symbol.upper()
    base, quote = (s[:-4], s[-4:]) if s.endswith("USDT") else (s[:-3], s[-3:]) if s.endswith("USD") else (s, "")
    base = "XBT" if base == "BTC" else base
    quote = "USD" if quote == "USDT" else (quote or "USD")
    return f"{base}{quote}"


def _bars_from_kraken(payload: dict) -> list[Bar]:
    """Kraken OHLC: {"error": [...], "result": {"<pair>": [[time, o, h, l, c, vwap, volume, count], ...]}}.
    The pair key under `result` varies (XXBTZUSD etc.), so we take the first non-"last" series."""
    result = payload.get("result", {})
    rows: list = []
    for key, value in result.items():
        if key == "last":
            continue
        rows = value
        break
    out: list[Bar] = []
    for row in rows:
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(row[0]), tz=UTC),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[6])),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def _bars_from_bybit(payload: dict) -> list[Bar]:
    """Bybit v5 kline: {"result": {"list": [[startMs, open, high, low, close, volume, turnover], ...]}}.
    The list is NEWEST-first; re-sort ascending so the contract matches every other provider."""
    rows = payload.get("result", {}).get("list", [])
    out: list[Bar] = []
    for row in rows:
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            )
        )
    return sorted(out, key=lambda b: b.ts)


def _bars_from_yahoo(payload: dict) -> list[Bar]:
    """Yahoo chart API: result[0] has `timestamp` (epoch seconds) and parallel indicators.quote[0]
    OHLCV arrays. Yahoo emits None for gap days (holidays); those rows are skipped, not zero-filled."""
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return []
    res = results[0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens, highs, lows, closes, volumes = (
        quote.get("open") or [], quote.get("high") or [], quote.get("low") or [],
        quote.get("close") or [], quote.get("volume") or [],
    )
    out: list[Bar] = []
    for i, ts in enumerate(timestamps):
        o, h, lo, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, lo, c):  # Yahoo gap day — no bar, never zero-fill (that would fabricate price)
            continue
        out.append(
            Bar(
                ts=datetime.fromtimestamp(int(ts), tz=UTC),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(lo)),
                close=Decimal(str(c)),
                volume=Decimal(str(volumes[i] if i < len(volumes) and volumes[i] is not None else 0)),
            )
        )
    return sorted(out, key=lambda b: b.ts)
