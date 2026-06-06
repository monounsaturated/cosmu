from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ._types import AltDataPoint, _ssl_context


class FredMacroProvider:
    """FRED/ALFRED macro series (free API, numeric → no LLM). `metric` is the FRED series id (e.g. "T10Y2Y"
    curve slope, "DGS10" 10y, "VIXCLS"). Cross-asset: one macro read conditions risk premia across every class.

    POINT-IN-TIME (look-ahead fix): the default `series/observations` returns the LATEST REVISED value for each
    date — a back-test reading that value at `date + 1d` is using a number that did NOT exist then (GDP, CPI and
    most macro series are revised for months/years). We request `output_type=4` (ALFRED "initial release only"),
    so each observation is the value as FIRST PUBLISHED and carries `realtime_start` = its first-published date.
    We stamp `available_at = realtime_start` — the honest first-known time — instead of a fabricated next-day
    floor. (`release_lag_days` is kept only as a defensive fallback for a row missing realtime_start.)
    Offline-testable via an injected `_fetcher(url) -> dict` (canned ALFRED payload; no live network in tests)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.stlouisfed.org/fred",
        release_lag_days: int = 1,
        *,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.release_lag_days = release_lag_days
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        # output_type=4 → ALFRED "initial release only": one row per date = the value as FIRST published, with
        # realtime_start = its first-publish date. This is the vintage-safe, no-look-ahead read.
        params = {
            "series_id": metric, "file_type": "json", "sort_order": "desc",
            "output_type": 4, "limit": min(limit, 100000),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.base_url}/series/observations?{urllib.parse.urlencode(params)}"
        payload = self._fetcher(url)
        out: list[AltDataPoint] = []
        for row in payload.get("observations", []):
            if row.get("value") in (None, ".", ""):  # FRED uses "." for missing
                continue
            ts = datetime.fromisoformat(row["date"]).replace(tzinfo=UTC)
            # available_at = the FIRST-RELEASE date (realtime_start). Fall back to the next-day floor only when a
            # row omits it. max(., ts) guards against a realtime_start that predates the period end (never < ts).
            rt_raw = row.get("realtime_start")
            if rt_raw:
                available_at = max(ts, datetime.fromisoformat(rt_raw).replace(tzinfo=UTC))
            else:
                available_at = ts + timedelta(days=self.release_lag_days)
            out.append(AltDataPoint(ts=ts, available_at=available_at, value=float(row["value"])))
        return sorted(out, key=lambda p: p.ts)


def _points_from_cboe_putcall(csv_text: str, release_lag_days: int) -> list[AltDataPoint]:
    """CBOE total put/call CSV: a few preamble lines then `DATE,PUT/CALL RATIO` (or `Date,...`). Each
    session's ratio is finalized after the close → available `release_lag_days` later (next-day floor)."""
    out: list[AltDataPoint] = []
    for line in csv_text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 2:
            continue
        date_raw, value_raw = cols[0], cols[1]
        ts = _parse_cboe_date(date_raw)
        if ts is None:
            continue  # header/preamble line
        try:
            value = float(value_raw)
        except ValueError:
            continue
        out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=release_lag_days), value=value))
    return sorted(out, key=lambda p: p.ts)


def _parse_cboe_date(raw: str) -> datetime | None:
    """CBOE dates appear as MM/DD/YYYY or YYYY-MM-DD; return None for non-date cells (headers)."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class CboePutCallProvider:
    """CBOE free total put/call ratio (daily CSV, no key). Market-wide metric "putcall_ratio"; symbol
    ignored (one series for the whole tape). The ratio for a session is finalized AFTER the close, so each
    point is stamped available the NEXT day — a conservative point-in-time floor, never look-ahead."""

    def __init__(self, url: str = "https://cdn.cboe.com/api/global/us_indices/daily_prices/total_pc.csv", release_lag_days: int = 1, *, _fetcher: Callable[[str], str] | None = None) -> None:
        self.url = url
        self.release_lag_days = release_lag_days
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> str:
        # CBOE's CDN 403s a bare bot UA — present a browser-like UA + Accept so the free CSV is served.
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "text/csv,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return resp.read().decode("utf-8")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "putcall_ratio":
            return []
        text = self._fetcher(self.url)
        return _points_from_cboe_putcall(text, self.release_lag_days)[-limit:]
