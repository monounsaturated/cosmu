from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ._types import AltDataPoint, _ssl_context


class FundingRateProvider:
    """Binance USDⓈ-M funding rate (free REST). Numeric → no LLM. Used as a long filter (spot)."""

    def __init__(self, base_url: str = "https://fapi.binance.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "funding_rate":
            return []
        query = urllib.parse.urlencode({"symbol": symbol, "limit": min(limit, 1000)})
        url = f"{self.base_url}/fapi/v1/fundingRate?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["fundingTime"]) / 1000, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["fundingRate"])))
        return out


class CachedFundingRateProvider:
    """Offline funding-rate provider backed by an on-disk cache of REAL Binance USDⓈ-M funding history
    (mirrors the bar-cache pattern). The cache is a per-symbol JSON of `[{fundingTime: ms, fundingRate: str}]`
    rows fetched ONCE from the live REST endpoint (see scripts/cache_funding.py) so the carry/neutral Gate can
    run deterministically with no network. `available_at == ts == fundingTime` (the exchange publishes the
    realized rate at the funding instant — that IS the point-in-time stamp; no look-ahead). A missing cache file
    yields an empty series (the funding feature then reads None — an honest 'no data', never a fabricated rate)."""

    def __init__(self, cache_dir: Path | str = ".cosmu/market_data/binance_funding") -> None:
        self.cache_dir = Path(cache_dir)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "funding_rate":
            return []
        path = self.cache_dir / f"{symbol}.json"
        if not path.exists():
            return []
        rows = json.loads(path.read_text())
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["fundingTime"]) / 1000, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["fundingRate"])))
        out.sort(key=lambda p: p.ts)
        return out[-limit:] if limit and len(out) > limit else out


class BinanceFundingHistoryProvider:
    """Paginated Binance USDⓈ-M funding-rate HISTORY (free `fapi/v1/fundingRate`, no key). The single-page
    `FundingRateProvider` tops out at the endpoint's 1000-row cap (~111 days at 8h funding); this walks
    `startTime` forward one page at a time until it reaches `now` (or `end_ms`), so ONE call yields ≥1 year
    of history per symbol. `available_at == ts == fundingTime` — the exchange publishes the realized rate at
    the funding instant, which IS the point-in-time stamp (no look-ahead). The walk de-dups by fundingTime so
    an overlapping page boundary never double-counts. Offline-testable: inject `_fetcher(url) -> list` to
    replay canned pages; tests never touch the network (live runs sleep `sleep_s` between pages to stay polite)."""

    def __init__(
        self,
        base_url: str = "https://fapi.binance.com",
        *,
        page_limit: int = 1000,
        sleep_s: float = 0.25,
        max_pages: int = 5000,
        _fetcher: Callable[[str], list] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.page_limit = max(1, min(page_limit, 1000))  # Binance hard-caps the page at 1000 rows
        self.sleep_s = sleep_s
        self.max_pages = max_pages
        self._live = _fetcher is None  # only the live path sleeps between pages
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> list:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=25, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_history(self, symbol: str, *, start_ms: int, end_ms: int | None = None) -> list[AltDataPoint]:
        """Walk pages forward from `start_ms` to `end_ms` (default = now). Returns ascending, de-duped
        AltDataPoints. A short (<page_limit) page means the history is exhausted → stop."""
        import time

        end = int(end_ms) if end_ms is not None else int(time.time() * 1000)
        cursor = int(start_ms)
        seen: set[int] = set()
        out: list[AltDataPoint] = []
        for _ in range(self.max_pages):
            if cursor > end:
                break
            params = {"symbol": symbol, "startTime": cursor, "endTime": end, "limit": self.page_limit}
            url = f"{self.base_url}/fapi/v1/fundingRate?{urllib.parse.urlencode(params)}"
            rows = self._fetcher(url)
            if not rows:
                break
            last_ft = cursor
            for row in rows:
                ft = int(row["fundingTime"])
                last_ft = max(last_ft, ft)
                if ft in seen:
                    continue
                seen.add(ft)
                ts = datetime.fromtimestamp(ft / 1000, tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["fundingRate"])))
            if len(rows) < self.page_limit:
                break  # last partial page → no more history
            nxt = last_ft + 1
            if nxt <= cursor:
                break  # no forward progress (defensive against a stuck cursor)
            cursor = nxt
            if self._live and self.sleep_s:
                time.sleep(self.sleep_s)
        out.sort(key=lambda p: p.ts)
        return out

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """AltDataProvider seam: the trailing `limit` funding points (covers ~limit/3 days at 8h funding).
        Backfills should call `fetch_history` with an explicit `start_ms` for a full ≥1yr span instead."""
        if metric != "funding_rate":
            return []
        import time

        days = max(1, int(limit / 3) + 2)  # 3 funding events/day → enough lookback to fill `limit` rows
        start_ms = int((time.time() - days * 86400) * 1000)
        pts = self.fetch_history(symbol, start_ms=start_ms)
        return pts[-limit:] if limit and len(pts) > limit else pts


class OkxFundingRateProvider:
    """OKX perpetual-swap funding rate history (public REST, no key required).

    Fetches /api/v5/public/funding-rate-history for a given -SWAP symbol and
    returns ascending AltDataPoints.  `available_at == ts == fundingTime` (the
    exchange publishes the realized rate at the funding instant — that IS the
    point-in-time stamp; no look-ahead).  A missing symbol or network error
    yields [] (honest 'no data', never a fabricated rate).

    Funding interval: OKX settles every 8 h (00:00, 08:00, 16:00 UTC) on most
    perpetuals, matching Binance.  Walk `after` cursor backward page-by-page to
    collect full history; the public endpoint returns up to 100 rows per page.

    Offline-testable: inject `_fetcher(url) -> list[dict]` to replay canned
    responses — tests never touch the network.
    """

    _BASE = "https://www.okx.com"
    _PAGE = 100  # OKX hard-caps funding-rate-history at 100 rows per page

    def __init__(
        self,
        base_url: str = _BASE,
        *,
        sleep_s: float = 0.2,
        max_pages: int = 5000,
        _fetcher: "Callable[[str], list] | None" = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sleep_s = sleep_s
        self.max_pages = max_pages
        self._live = _fetcher is None
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> list:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("data", [])
        except Exception:  # noqa: BLE001 — network errors degrade to empty, never crash
            return []

    def fetch_history(self, symbol: str, *, start_ms: int, end_ms: int | None = None) -> list[AltDataPoint]:
        """Paginate OKX funding-rate history for `symbol` from `start_ms` to now (or `end_ms`).

        OKX paginates via `after` (exclusive upper cursor on fundingTime ms) so each
        page walks BACKWARD.  We collect all pages then filter by start_ms and deduplicate.
        """
        import time as _time

        end = int(end_ms) if end_ms is not None else int(_time.time() * 1000)  # noqa: F841
        seen: set[int] = set()
        out: list[AltDataPoint] = []
        after: int | None = None  # None = start from the latest page
        for _ in range(self.max_pages):
            params: dict = {"instId": symbol, "limit": self._PAGE}
            if after is not None:
                params["after"] = after
            url = f"{self.base_url}/api/v5/public/funding-rate-history?{urllib.parse.urlencode(params)}"
            rows = self._fetcher(url)
            if not rows:
                break
            for row in rows:
                ft = int(row["fundingTime"])
                if ft in seen:
                    continue
                seen.add(ft)
                if ft < start_ms:
                    continue
                ts = datetime.fromtimestamp(ft / 1000, tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["realizedRate"])))
            # The oldest fundingTime on this page becomes the next `after` cursor
            oldest_ft = min(int(r["fundingTime"]) for r in rows)
            if oldest_ft <= start_ms:
                break  # no more history before our window
            after = oldest_ft
            if len(rows) < self._PAGE:
                break  # short page → history exhausted
            if self._live and self.sleep_s:
                _time.sleep(self.sleep_s)
        out.sort(key=lambda p: p.ts)
        return out

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """AltDataProvider seam: trailing `limit` funding points (~limit/3 days at 8 h funding)."""
        if metric != "funding_rate":
            return []
        import time as _time

        days = max(1, int(limit / 3) + 2)
        start_ms = int((_time.time() - days * 86400) * 1000)
        try:
            pts = self.fetch_history(symbol, start_ms=start_ms)
        except Exception:  # noqa: BLE001 — injected fetchers may raise; degrade to empty
            return []
        return pts[-limit:] if limit and len(pts) > limit else pts


class KrakenFuturesFundingRateProvider:
    """Kraken Futures historical funding rates (public REST, no key required).

    Fetches /api/v3/historicalfundingrates for PF_-prefixed linear perpetuals.
    `available_at == ts` (Kraken publishes the realized premium at its effective
    time — no look-ahead).  Kraken Futures settles funding on an hourly basis via
    a premium index; rates are expressed per-interval (convert to 8h-equivalent
    in the dispersion strategy if comparing cross-venue).

    Offline-testable via the injected `_fetcher(url) -> list[dict]` callable.
    Falls back to [] on any network / parse error.
    """

    _BASE = "https://futures.kraken.com"

    def __init__(
        self,
        base_url: str = _BASE,
        *,
        sleep_s: float = 0.2,
        _fetcher: "Callable[[str], list] | None" = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.sleep_s = sleep_s
        self._live = _fetcher is None
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> list:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("rates", [])
        except Exception:  # noqa: BLE001
            return []

    def fetch_history(self, symbol: str, *, start_ms: int, end_ms: int | None = None) -> list[AltDataPoint]:
        """Fetch all funding rate entries for `symbol` from `start_ms` to now (or `end_ms`).

        Kraken returns the full history in one request (no pagination cursor needed
        for most symbols).  Filter to [start_ms, end_ms] and deduplicate.
        """
        import time as _time

        end = int(end_ms) if end_ms is not None else int(_time.time() * 1000)
        url = f"{self.base_url}/api/v3/historicalfundingrates?symbol={urllib.parse.quote(symbol)}"
        try:
            rows = self._fetcher(url)
        except Exception:  # noqa: BLE001
            return []
        seen: set[int] = set()
        out: list[AltDataPoint] = []
        for row in rows:
            # Kraken returns effectiveTime as a millisecond Unix epoch integer
            ft = int(row["timestamp"])
            if ft in seen or ft < start_ms or ft > end:
                continue
            seen.add(ft)
            ts = datetime.fromtimestamp(ft / 1000, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["fundingRate"])))
        out.sort(key=lambda p: p.ts)
        return out

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """AltDataProvider seam: trailing `limit` funding points."""
        if metric != "funding_rate":
            return []
        import time as _time

        days = max(1, int(limit / 24) + 2)  # ~24 events/day at 1h settlement
        start_ms = int((_time.time() - days * 86400) * 1000)
        try:
            pts = self.fetch_history(symbol, start_ms=start_ms)
        except Exception:  # noqa: BLE001
            return []
        return pts[-limit:] if limit and len(pts) > limit else pts
