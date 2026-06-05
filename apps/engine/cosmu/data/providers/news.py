from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ._types import AltDataPoint, NewsItem, _ssl_context


def _gdelt_query(coin: str) -> str:
    """Map a coin ticker to a GDELT keyword query. Tickers alone are too noisy, so the common majors get a
    name; everything else falls back to the ticker plus "crypto" to keep the topic anchored."""
    names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin"}
    return names.get(coin.upper(), f"{coin} crypto")


def _parse_gdelt_date(raw: str) -> datetime | None:
    """GDELT seendate is "YYYYMMDDTHHMMSSZ" (sometimes "YYYYMMDDHHMMSS"). Return None if unparseable."""
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _news_from_gdelt(payload: dict) -> list[NewsItem]:
    """GDELT ArtList JSON: {"articles": [{"title", "seendate": "YYYYMMDDTHHMMSSZ", "url"}]}. `seendate`
    is when GDELT indexed it — its point-in-time availability (ts == available_at; we knew it then)."""
    out: list[NewsItem] = []
    for art in payload.get("articles", []) or []:
        title = (art.get("title") or "").strip()
        seen = art.get("seendate")
        if not title or not seen:
            continue
        ts = _parse_gdelt_date(seen)
        if ts is None:
            continue
        out.append(NewsItem(ts=ts, available_at=ts, headline=title))
    return sorted(out, key=lambda n: n.ts)


def _points_from_gdelt_tone(payload: dict, limit: int) -> list[AltDataPoint]:
    """GDELT TimelineTone JSON: {"timeline": [{"data": [{"date": "YYYYMMDDHHMMSS", "value": float}]}]}.
    `available_at = ts + 1 day` — a day's indexed articles are closed by end-of-day; the next-day
    conservative floor means we never read the future. Deduplicates by ts (latest wins)."""
    seen: dict[datetime, AltDataPoint] = {}
    for series in payload.get("timeline", []) or []:
        for row in (series.get("data", []) or []):
            date_raw = row.get("date")
            value_raw = row.get("value")
            if not date_raw or value_raw is None:
                continue
            ts = _parse_gdelt_date(date_raw)
            if ts is None:
                continue
            seen[ts] = AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=float(value_raw))
    out = sorted(seen.values(), key=lambda p: p.ts)
    return out[-limit:] if limit and len(out) > limit else out


class GdeltNewsProvider:
    """Real free news via the GDELT 2.0 doc API (no key). Returns NewsItem headlines stamped point-in-time
    (a headline's `seendate` IS its availability time — we knew it when GDELT indexed it, never before).
    Standardization to a numeric sentiment series still happens ONCE downstream at ingest (the LLM seam),
    never here. Offline tests use FixtureNewsProvider; this is the live path."""

    def __init__(self, base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc", timespan: str = "3d") -> None:
        self.base_url = base_url.rstrip("/")
        self.timespan = timespan

    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode(
            {"query": _gdelt_query(coin), "mode": "ArtList", "format": "json", "maxrecords": min(limit, 250), "timespan": self.timespan, "sort": "DateAsc"}
        )
        url = f"{self.base_url}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _news_from_gdelt(payload)[-limit:]


class GdeltToneProvider:
    """GDELT v2 geopolitical/news tone as a daily numeric series (keyless, free, EU-accessible). Queries
    risk/geopolitical keywords via GDELT's TimelineTone API → one average-tone value per day in the range
    [-100, +100] (negative = negative sentiment, positive = positive). Market-wide: the query covers global
    risk themes, not a single asset. `available_at = ts + 1 day` — a day's indexed articles are closed by
    end-of-day; the conservative next-day floor means we never read the future. Offline-testable via an
    injected `_fetcher(url) -> dict`. One dead fetch → [] (never aborts the run)."""

    DEFAULT_QUERY = "crisis war sanctions recession inflation geopolitical risk conflict tariff"

    def __init__(
        self,
        base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc",
        query: str | None = None,
        timespan: str = "30d",
        *,
        _fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.query = query or self.DEFAULT_QUERY
        self.timespan = timespan
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "gdelt_tone":
            return []
        params = {
            "query": self.query,
            "mode": "TimelineTone",
            "format": "json",
            "timespan": self.timespan,
            "sort": "DateAsc",
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        try:
            payload = self._fetcher(url)
        except Exception:  # noqa: BLE001
            return []
        return _points_from_gdelt_tone(payload, limit)


class OsintAirActivityProvider:
    """Adapts the OpenSky ADS-B data source to the AltDataProvider protocol for the ingest loop."""

    def __init__(self, offline: bool = False) -> None:
        self.offline = offline

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "osint_air_activity":
            return []
        from cosmu.data.sources.osint_adsb import AdsbDataSource
        src = AdsbDataSource(offline=self.offline)
        payload = src._fetch_payload()
        from cosmu.data.sources.osint_adsb import _count_in_bbox, _DEFAULT_BBOX
        count = _count_in_bbox(payload, _DEFAULT_BBOX)
        now = datetime.now(UTC)
        return [AltDataPoint(ts=now, available_at=now, value=float(count))]
