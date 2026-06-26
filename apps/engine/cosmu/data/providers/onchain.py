from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ._types import AltDataPoint, _ssl_context


def _points_from_deribit_dvol(payload: dict, limit: int) -> list[AltDataPoint]:
    """Deribit get_volatility_index_data: {"result": {"data": [[ts_ms, open, high, low, close], ...]}}.
    We use the `close` (daily DVOL value at bar-end). `available_at = ts + 1 day` — a daily bar opens at
    midnight UTC and is finalized at end-of-day; the next-day floor means we never claim today's close
    before it happens. Rows with zero or negative close are dropped (Deribit occasionally emits nulls)."""
    rows = (payload.get("result") or {}).get("data") or []
    out: list[AltDataPoint] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        ts_ms, close = row[0], row[4]
        if close is None:
            continue
        close_f = float(close)
        if close_f <= 0:
            continue
        ts = datetime.fromtimestamp(int(ts_ms) / 1000, tz=UTC)
        out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=close_f))
    out.sort(key=lambda p: p.ts)
    return out[-limit:] if limit and len(out) > limit else out


class DefiLlamaTvlProvider:
    """DeFiLlama total DeFi TVL (free, no key). Market-wide metric. TVL for a day is finalized
    after the day closes, so each point is stamped available the NEXT day — no look-ahead."""

    def __init__(self, url: str = "https://api.llama.fi/v2/historicalChainTvl") -> None:
        self.url = url

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "defi_tvl":
            return []
        req = urllib.request.Request(self.url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
        out: list[AltDataPoint] = []
        for row in payload[-limit:] if isinstance(payload, list) else []:
            ts = datetime.fromtimestamp(int(row.get("date", 0)), tz=UTC)
            tvl = float(row.get("tvl", 0))
            if tvl > 0:
                out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=tvl))
        return sorted(out, key=lambda p: p.ts)


class ExchangeNetflowProvider:
    """Exchange net deposit/withdrawal flow proxy via Binance USDⓈ-M long/short ratio (free REST).
    Positive = net longs building (inflow proxy); negative = net shorts (outflow pressure).
    Offline-testable via an injected `_fetcher(url) -> list` (canned payload; no live network in tests)."""

    def __init__(self, base_url: str = "https://fapi.binance.com", *, _fetcher: Callable[[str], list] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> list:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "exchange_netflow":
            return []
        query = urllib.parse.urlencode({"symbol": symbol, "period": "1h", "limit": min(limit, 500)})
        url = f"{self.base_url}/futures/data/globalLongShortAccountRatio?{query}"
        rows = self._fetcher(url)
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC)
            ratio = float(row.get("longShortRatio", 1.0))
            out.append(AltDataPoint(ts=ts, available_at=ts, value=ratio - 1.0))
        return sorted(out, key=lambda p: p.ts)


class BinanceOpenInterestProvider:
    """Binance USDⓈ-M aggregate open interest (free REST, no key). Numeric; availability == publication.
    Offline-testable via an injected `_fetcher(url) -> list` (canned payload; no live network in tests)."""

    def __init__(self, base_url: str = "https://fapi.binance.com", *, _fetcher: Callable[[str], list] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> list:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "open_interest":
            return []
        query = urllib.parse.urlencode({"symbol": symbol, "period": "1h", "limit": min(limit, 500)})
        url = f"{self.base_url}/futures/data/openInterestHist?{query}"
        rows = self._fetcher(url)
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row.get("sumOpenInterestValue", row.get("sumOpenInterest", 0)))))
        return sorted(out, key=lambda p: p.ts)


class BinanceBasisProvider:
    """Binance USDⓈ-M perpetual vs spot basis (free REST). Computed as (mark - index) / index.
    Offline-testable via an injected `_fetcher(url) -> dict` (canned payload; no live network in tests)."""

    def __init__(self, base_url: str = "https://fapi.binance.com", *, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "perp_spot_basis":
            return []
        url = f"{self.base_url}/fapi/v1/premiumIndex?{urllib.parse.urlencode({'symbol': symbol})}"
        row = self._fetcher(url)
        mark = float(row.get("markPrice", 0))
        index = float(row.get("indexPrice", 0))
        if index == 0:
            return []
        basis = (mark - index) / index
        ts = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC)
        return [AltDataPoint(ts=ts, available_at=ts, value=basis)]


class DeribitDvolProvider:
    """Deribit BTC/ETH implied volatility index (DVOL) — free public REST, no key, EU-native (Netherlands).
    DVOL is Deribit's 30-day forward implied vol for BTC or ETH options — the crypto equivalent of VIX.
    Per-symbol (BTCUSDT → BTC, ETHUSDT → ETH); unknown symbols → []. `available_at = ts + 1 day`:
    each daily bar starts at midnight UTC and is finalized at end-of-day; the conservative next-day floor
    means we never claim to know today's close before it happens. Offline-testable via an injected
    `_fetcher(url) -> dict`. One dead fetch → [] (never aborts the run)."""

    _CURRENCY = {"BTC": "BTC", "ETH": "ETH"}

    def __init__(
        self,
        base_url: str = "https://www.deribit.com/api/v2",
        resolution: int = 86400,
        days_back: int = 60,
        *,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.resolution = resolution
        self.days_back = days_back
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "dvol":
            return []
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        currency = self._CURRENCY.get(coin.upper())
        if currency is None:
            return []
        import time as _time

        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - self.days_back * 86400 * 1000
        params = {
            "currency": currency,
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": str(self.resolution),
        }
        url = f"{self.base_url}/public/get_volatility_index_data?{urllib.parse.urlencode(params)}"
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001
            return []
        return _points_from_deribit_dvol(payload, limit)
