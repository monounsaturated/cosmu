# intent: a point-in-time-safe seam for social/alt data (LunarCrush etc.) feeding the gate and, later, the LLM feature factory; inputs: provider pulls; outputs: ordered AltDataPoint series readable "as of" a time; invariants: every point carries an availability time, snapshots are append-only (vendors revise history — we never overwrite), transforms are causal (rolling only), and secrets stay server-side.

from __future__ import annotations

import json
import math
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections.abc import Callable
from typing import Any, Protocol


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs (sandbox, slim images)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


@dataclass(frozen=True)
class AltDataPoint:
    ts: datetime  # the metric's observation time (aligns to a bar)
    available_at: datetime  # when we would actually have known it — the point-in-time stamp
    value: float


class AltDataProvider(Protocol):
    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Return ascending alt-data points for one symbol/metric."""


class AltDataStore:
    """Append-only, point-in-time snapshot store. One JSONL file per provider/symbol/metric; each
    append is a new immutable line. Reads filter to `available_at <= as_of`, so a later vendor
    revision can never rewrite what you would have known earlier."""

    def __init__(self, root: Path | str = ".cosmu/altdata") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str, symbol: str, metric: str) -> Path:
        safe = f"{provider}_{symbol}_{metric}".replace("/", "")
        return self.root / f"{safe}.jsonl"

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        path = self._path(provider, symbol, metric)
        with path.open("a") as fh:
            for p in points:
                fh.write(json.dumps({"ts": p.ts.isoformat(), "available_at": p.available_at.isoformat(), "value": p.value}) + "\n")

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        path = self._path(provider, symbol, metric)
        if not path.exists():
            return []
        # Last write wins per ts among rows already available by `as_of` (revisions append, newest used).
        latest: dict[str, AltDataPoint] = {}
        for line in path.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            available = datetime.fromisoformat(row["available_at"])
            if available > as_of:
                continue
            latest[row["ts"]] = AltDataPoint(ts=datetime.fromisoformat(row["ts"]), available_at=available, value=float(row["value"]))
        return sorted(latest.values(), key=lambda p: p.ts)

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Every appended point, every revision, sorted by availability — the full point-in-time history.
        A backtest's per-bar as-of join (it keeps the latest value with available_at <= bar time) needs the
        whole revision trail, so this does NOT collapse revisions the way read_asof does."""
        path = self._path(provider, symbol, metric)
        if not path.exists():
            return []
        out: list[AltDataPoint] = []
        for line in path.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            out.append(AltDataPoint(ts=datetime.fromisoformat(row["ts"]), available_at=datetime.fromisoformat(row["available_at"]), value=float(row["value"])))
        return sorted(out, key=lambda p: (p.available_at, p.ts))


class LunarCrushProvider:
    """LunarCrush v4 social metrics over HTTP (stdlib, no extra dep). KEY-GATED: the key is server-side only,
    and with NO key the provider returns [] so the system degrades honestly (it never fabricates a social read).
    Our semantic metric names map to the LunarCrush v4 coin time-series fields (`_FIELD`). Availability defaults
    to one bar after observation (a day's social data is known only after the day closes — point-in-time, no
    look-ahead). Low-confidence/tier1 until it earns its place out-of-sample."""

    # semantic metric (feature_registry name) -> LunarCrush v4 coin time-series field
    _FIELD = {"social_volume": "social_volume", "social_sentiment": "sentiment", "galaxy_score": "galaxy_score"}

    def __init__(self, api_key: str = "", base_url: str = "https://lunarcrush.com/api4/public", *, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if not self.api_key:  # honest degradation — no key, no data (never a fabricated read)
            return []
        field = self._FIELD.get(metric)
        if field is None:
            return []
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode({"bucket": "day"})
        url = f"{self.base_url}/coins/{coin}/time-series/v2?{query}"
        payload = self._fetcher(url)
        out: list[AltDataPoint] = []
        for row in payload.get("data", [])[-limit:]:
            if row.get(field) is None:
                continue
            ts = datetime.fromtimestamp(int(row["time"]), tz=UTC)
            available = datetime.fromtimestamp(int(row["time"]) + 86400, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=available, value=float(row[field])))
        return out


class RedditSentimentProvider:
    """Reddit crowd sentiment from public `hot.json` listings (no auth, free). Market-wide proxy: scans a few
    crypto/markets subreddits, scores each post title with a small bull/bear lexicon, and reduces to ONE value
    in [-1, 1] = (bull - bear) / total. A real-time public feed → available_at == observation time (we know it
    when we read it; no look-ahead). Offline-testable via an injected `_fetcher`. One dead subreddit is swallowed
    (never aborts the read); zero scored posts → [] (honest, never a fabricated 0)."""

    SUBREDDITS = ("cryptocurrency", "bitcoin", "wallstreetbets")
    _BULL = frozenset({
        "moon", "bull", "bullish", "pump", "buy", "buying", "long", "rally", "breakout", "ath",
        "surge", "green", "rip", "hodl", "accumulate", "undervalued", "rocket", "up",
    })
    _BEAR = frozenset({
        "bear", "bearish", "dump", "crash", "sell", "selling", "short", "rug", "rekt", "red",
        "capitulation", "fear", "drop", "overvalued", "scam", "bubble", "down", "puts",
    })

    def __init__(self, subreddits: tuple[str, ...] | None = None, *, post_limit: int = 50, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.subreddits = tuple(subreddits) if subreddits else self.SUBREDDITS
        self.post_limit = post_limit
        self._fetcher = _fetcher or self._fetch

    # Reddit throttles/blocks bare bot UAs (429/empty); its API rules want a descriptive
    # `platform:appid:version (by /u/...)` agent — without this the live read silently yielded nothing.
    _UA = "python:cosmu-engine:0.1 (by /u/cosmu-bot)"

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": self._UA})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "reddit_sentiment":
            return []
        bull = bear = total = 0
        for sub in self.subreddits:
            url = f"https://www.reddit.com/r/{sub}/hot.json?{urllib.parse.urlencode({'limit': self.post_limit})}"
            try:
                payload = self._fetcher(url)
            except Exception:  # noqa: BLE001 — one dead subreddit never aborts the read
                continue
            for child in (payload.get("data", {}) or {}).get("children", []) or []:
                title = ((child.get("data", {}) or {}).get("title") or "")
                tokens = set(re.findall(r"[a-z']+", title.lower()))
                if not tokens:
                    continue
                total += 1
                if tokens & self._BULL:
                    bull += 1
                elif tokens & self._BEAR:
                    bear += 1
        if total == 0:
            return []
        score = (bull - bear) / total  # naturally in [-1, 1] since bull, bear <= total
        now = datetime.now(tz=UTC)
        return [AltDataPoint(ts=now, available_at=now, value=score)]


class FixtureAltDataProvider:
    """Deterministic synthetic provider so the gate builds and tests run with no key/network."""

    def __init__(self, series: dict[tuple[str, str], list[AltDataPoint]]) -> None:
        self.series = series
        self.calls: list[tuple[str, str, int]] = []

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        self.calls.append((symbol, metric, limit))
        return self.series.get((symbol, metric), [])[-limit:]


@dataclass(frozen=True)
class NewsItem:
    ts: datetime  # headline timestamp
    available_at: datetime  # when we'd have seen it (point-in-time)
    headline: str


class NewsProvider(Protocol):
    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        """Return ascending unstructured headlines for one symbol."""


class PgAltDataStore:
    """Central, append-only, point-in-time alt-data store backed by the Postgres `alt_data` table —
    the production replacement for the JSONL `AltDataStore`. Drop-in: same append/read_asof interface,
    so the ingestion pipeline doesn't change. Reads return the latest-revised value per ts that was
    available by `as_of`, so vendor revisions never rewrite history."""

    def __init__(self, store: Any) -> None:  # store: knowledge.store.Store (avoid import cycle)
        self.store = store

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        from cosmu.knowledge.store import utcnow

        if not points:
            return
        now = utcnow()
        with self.store.batch() as writer:
            for p in points:
                writer._con.execute(
                    "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (provider, symbol, metric, p.ts.isoformat(), p.available_at.isoformat(), float(p.value), now),
                )

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list[AltDataPoint]:
        rows = self.store.rows(
            "SELECT DISTINCT ON (ts) ts, available_at, value FROM alt_data "
            "WHERE provider = ? AND symbol = ? AND metric = ? AND available_at <= ? "
            "ORDER BY ts, id DESC",
            (provider, symbol, metric, as_of.isoformat()),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        """Full revision history (see AltDataStore.read_all) — the per-bar as-of join collapses it correctly."""
        rows = self.store.rows(
            "SELECT ts, available_at, value FROM alt_data WHERE provider = ? AND symbol = ? AND metric = ? ORDER BY available_at, id",
            (provider, symbol, metric),
        )
        return [AltDataPoint(ts=datetime.fromisoformat(r["ts"]), available_at=datetime.fromisoformat(r["available_at"]), value=float(r["value"])) for r in rows]


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
        page walks BACKWARD.  We collect all pages then filter to [start_ms, end] and deduplicate.
        """
        import time as _time

        end = int(end_ms) if end_ms is not None else int(_time.time() * 1000)
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
                if ft < start_ms or ft > end:
                    continue  # respect [start_ms, end_ms]; end honours the point-in-time cutoff like the Binance sibling
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


class FearGreedProvider:
    """Crypto Fear & Greed index (alternative.me, free, daily). Market-wide; symbol ignored."""

    def __init__(self, base_url: str = "https://api.alternative.me") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "fear_greed":
            return []
        query = urllib.parse.urlencode({"limit": limit, "format": "json"})
        url = f"{self.base_url}/fng/?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in payload.get("data", []):
            ts = datetime.fromtimestamp(int(row["timestamp"]), tz=UTC)
            available = datetime.fromtimestamp(int(row["timestamp"]) + 86400, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=available, value=float(row["value"])))
        return sorted(out, key=lambda p: p.ts)


class FredMacroProvider:
    """FRED macro series (free API, numeric → no LLM). Each observation is stamped available the day
    AFTER its period (release lag is real for macro; next-day availability is a conservative floor).
    `metric` is the FRED series id (e.g. "T10Y2Y" curve slope, "DGS10" 10y, "VIXCLS"). Cross-asset:
    one macro read conditions risk premia across every class, so it feeds the cross-asset risk tag."""

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.stlouisfed.org/fred", release_lag_days: int = 1) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.release_lag_days = release_lag_days

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        params = {"series_id": metric, "file_type": "json", "sort_order": "desc", "limit": min(limit, 100000)}
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.base_url}/series/observations?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in payload.get("observations", []):
            if row.get("value") in (None, ".", ""):  # FRED uses "." for missing
                continue
            ts = datetime.fromisoformat(row["date"]).replace(tzinfo=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=self.release_lag_days), value=float(row["value"])))
        return sorted(out, key=lambda p: p.ts)


class PolymarketOddsProvider:
    """Polymarket public CLOB midpoint odds (free, no wallet). `metric` = a market's token id; the
    value is the implied probability in [0,1]. Odds-as-features only — NO execution in this pass.
    Numeric → no LLM. Continuous feed, so a price is available at its own timestamp (no lag)."""

    def __init__(self, base_url: str = "https://clob.polymarket.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        query = urllib.parse.urlencode({"market": metric, "fidelity": 1440})  # daily buckets
        url = f"{self.base_url}/prices-history?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in payload.get("history", [])[-limit:]:
            ts = datetime.fromtimestamp(int(row["t"]), tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row["p"])))
        return sorted(out, key=lambda p: p.ts)


class PolymarketGammaProvider:
    """Auto-discovers macro/risk markets via Polymarket's public Gamma API and aggregates their CLOB
    midpoint odds into a composite risk_on feature. No manual token needed.

    Discovery uses TWO passes: (1) the ``/events`` endpoint filtered by macro-relevant tags (Economy,
    Finance, Stocks, Geopolitics, Fiscal, Crypto Prices), extracting nested markets; (2) a keyword
    scan on ``/markets`` for any the events pass missed. Sorted by liquidity, top N aggregated.

    If ``pin_token`` is set, that specific market is always included (backward-compatible with the
    old single-token flow). Numeric → no LLM. Offline-testable via constructor injection of canned
    payloads (``_gamma_fetcher``)."""

    MACRO_TAGS = ("Economy", "Finance", "Stocks", "Fiscal", "Crypto Prices", "Taxes", "Macro Geopolitics")

    MACRO_KEYWORDS = (
        "recession", "gdp", "inflation", "cpi", "interest rate", "rate cut", "rate hike",
        "fed ", "federal reserve", "fomc", "unemployment", "jobs report", "tariff", "trade war",
        "stock market", "s&p 500", "s&p500", "dow jones", "nasdaq", "crash", "bear market",
        "economic", "economy", "debt ceiling", "default", "treasury", "bitcoin price",
        "btc price", "crypto price", "ipo", "invade", "invasion", "military clash",
        "sanctions", "nato", "war ",
    )

    def __init__(
        self,
        gamma_url: str = "https://gamma-api.polymarket.com",
        pin_token: str | None = None,
        max_markets: int = 8,
        *,
        _gamma_fetcher: Callable | None = None,
    ) -> None:
        self.gamma_url = gamma_url.rstrip("/")
        self.pin_token = pin_token
        self.max_markets = max_markets
        self._gamma_fetcher = _gamma_fetcher or self._fetch_gamma

    def _fetch_gamma(self, url: str) -> list | dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _extract_market_info(m: dict) -> dict | None:
        mid = m.get("id")
        if not mid:
            return None
        raw_prices = m.get("outcomePrices") or "[]"
        if isinstance(raw_prices, str):
            try:
                raw_prices = json.loads(raw_prices)
            except (json.JSONDecodeError, TypeError):
                raw_prices = []
        yes_prob = float(raw_prices[0]) if raw_prices else None
        liq = m.get("liquidity") or m.get("liquidityClob") or 0
        return {"id": str(mid), "question": m.get("question", ""), "liquidity": float(liq), "yes_prob": yes_prob}

    def _discover_via_events(self) -> list[dict]:
        macro_tags_lower = {t.lower() for t in self.MACRO_TAGS}
        seen: set[str] = set()
        hits: list[dict] = []
        for tag in self.MACRO_TAGS:
            url = f"{self.gamma_url}/events?tag={urllib.parse.quote(tag)}&closed=false&limit=30"
            try:
                events = self._gamma_fetcher(url)
            except Exception:
                continue
            if not isinstance(events, list):
                continue
            for ev in events:
                ev_tags = {(t.get("label") or "").lower() for t in (ev.get("tags") or [])}
                if not ev_tags & macro_tags_lower:
                    continue
                for m in ev.get("markets") or []:
                    if not m.get("active") or m.get("closed"):
                        continue
                    info = self._extract_market_info(m)
                    if not info or info["id"] in seen:
                        continue
                    seen.add(info["id"])
                    hits.append(info)
        return hits

    def _discover_via_keywords(self, exclude: set[str]) -> list[dict]:
        url = f"{self.gamma_url}/markets?closed=false&active=true&limit=100"
        try:
            raw = self._gamma_fetcher(url)
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        hits: list[dict] = []
        for m in raw:
            q = (m.get("question") or "").lower()
            if not any(kw in q for kw in self.MACRO_KEYWORDS):
                continue
            info = self._extract_market_info(m)
            if not info or info["id"] in exclude:
                continue
            hits.append(info)
        return hits

    def discover_markets(self) -> list[dict]:
        hits = self._discover_via_events()
        seen = {h["id"] for h in hits}
        hits.extend(self._discover_via_keywords(seen))
        hits.sort(key=lambda h: h["liquidity"], reverse=True)
        return hits[: self.max_markets]

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        markets = self.discover_markets()
        if not markets:
            return []
        probs = [m["yes_prob"] for m in markets if m.get("yes_prob") is not None]
        if not probs:
            return []
        avg = sum(probs) / len(probs)
        now = datetime.now(tz=UTC)
        return [AltDataPoint(ts=now, available_at=now, value=avg)]


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


class CoinglassLiquidationProvider:
    """Coinglass free liquidations history (no key on the public history endpoint). Numeric → no LLM.
    Per-symbol metric "liquidations" (total long+short USD liquidated in the bucket). Coinglass closes a
    bucket before it publishes it, so a bucket observed at time T is available at the NEXT bucket boundary
    (here +1 day for the daily interval) — a conservative point-in-time floor, never look-ahead."""

    def __init__(self, base_url: str = "https://open-api.coinglass.com", interval: str = "1d", bucket_seconds: int = 86400, *, _fetcher: Callable[[str], dict] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.interval = interval
        self.bucket_seconds = bucket_seconds
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "liquidations":
            return []
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode({"symbol": coin, "interval": self.interval})
        url = f"{self.base_url}/public/v2/liquidation_history?{query}"
        payload = self._fetcher(url)
        return _points_from_coinglass(payload, self.bucket_seconds)[-limit:]


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


class XaiTwitterProvider:
    """Thin re-export adapter so the ingest pipeline can import XaiTwitterProvider from altdata (the
    canonical provider namespace), while the implementation lives in data/sources/xai_twitter.py."""

    def __new__(cls, *args, **kwargs):  # noqa: ANN002, ANN003
        from cosmu.data.sources.xai_twitter import XaiTwitterProvider as _Real

        return _Real(*args, **kwargs)


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


class PolymarketClobProvider:
    """Thin adapter over PolymarketClobSource (data/sources/polymarket.py), which fetches full daily
    history via the CLOB prices-history endpoint. Three metrics: pm_implied_prob, pm_prob_velocity,
    pm_book_depth — each a daily time series going back to market inception (180-400+ rows typical)."""

    def __init__(self, pin_token: str | None = None) -> None:
        from cosmu.data.sources.polymarket import PolymarketClobSource
        self._src = PolymarketClobSource(pin_token=pin_token)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        return self._src.fetch_series(symbol, metric, limit=limit)


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


def _gdelt_query(coin: str) -> str:
    """Map a coin ticker to a GDELT keyword query. Tickers alone are too noisy, so the common majors get a
    name; everything else falls back to the ticker plus "crypto" to keep the topic anchored."""
    names = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin"}
    return names.get(coin.upper(), f"{coin} crypto")


def _points_from_coinglass(payload: dict, bucket_seconds: int) -> list[AltDataPoint]:
    """Coinglass liquidation_history: {"data": [{"createTime"/"t": ms, "longLiquidationUsd",
    "shortLiquidationUsd"} | {"turnoverNumber"/"value": usd}]}. Sum long+short into one total liquidated
    USD per bucket; a bucket observed at ts is available one bucket later (it closes before publication)."""
    rows = payload.get("data", []) or []
    out: list[AltDataPoint] = []
    for row in rows:
        raw_ts = row.get("createTime", row.get("t", row.get("time")))
        if raw_ts is None:
            continue
        ts_seconds = int(raw_ts) / 1000 if int(raw_ts) > 10**11 else int(raw_ts)
        ts = datetime.fromtimestamp(ts_seconds, tz=UTC)
        if "longLiquidationUsd" in row or "shortLiquidationUsd" in row:
            value = float(row.get("longLiquidationUsd", 0) or 0) + float(row.get("shortLiquidationUsd", 0) or 0)
        else:
            value = float(row.get("turnoverNumber", row.get("value", 0)) or 0)
        out.append(AltDataPoint(ts=ts, available_at=datetime.fromtimestamp(ts_seconds + bucket_seconds, tz=UTC), value=value))
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


def _parse_gdelt_date(raw: str) -> datetime | None:
    """GDELT seendate is "YYYYMMDDTHHMMSSZ" (sometimes "YYYYMMDDHHMMSS"). Return None if unparseable."""
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


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


# Default routing: the gate asks for a SEMANTIC metric name; the store keyed it under the ingesting
# provider. Market-wide metrics live under the "MARKET" symbol (one series for the whole tape).
_STORE_PROVIDER_OF = {
    "venue_fees_maker": "venue_fees",
    "venue_fees_taker": "venue_fees",
    "funding_rate": "binance",
    "fear_greed": "alternative.me",
    "news_sentiment": "news",
    "news_event_score": "news",  # typed event/news scorer: sign × magnitude, stored per-symbol
    "pm_risk_on": "polymarket",
    "macro_regime": "fred",
    "liquidation_cascade": "coinglass",
    "putcall_ratio": "cboe",
    "vix_level": "fred",
    "fed_funds_rate": "fred",
    "defi_tvl": "defillama",
    "open_interest": "binance",
    "perp_spot_basis": "binance",
    "exchange_netflow": "binance",
    "dxy": "fred",
    "yield_curve_2s10s": "fred",
    "credit_spread": "fred",
    "vix_term_slope": "fred",
    "osint_air_activity": "opensky",
    "pm_implied_prob": "polymarket",
    "pm_prob_velocity": "polymarket",
    "pm_book_depth": "polymarket",
    "reddit_sentiment": "reddit",
    "social_volume": "lunarcrush",
    "social_sentiment": "lunarcrush",
    "galaxy_score": "lunarcrush",
    "twitter_sentiment": "xai",
    "twitter_influencer_sentiment": "xai",
    # Geopolitical news tone (GDELT, keyless, market-wide) and crypto options IV (Deribit, keyless, per-symbol).
    "gdelt_tone": "gdelt",
    "dvol": "deribit",
    # LLM qualitative→quantitative index scores (market-wide; the LLM standardizes text only, never the money path).
    "reg_risk_crypto": "llm_index",
    "risk_on_off": "llm_index",
    # Cross-asset daily price levels (free, no key) via Stooq/Yahoo — metals, commodities, equity indexes, FX.
    "gold_xau": "stooq",
    "silver_xag": "stooq",
    "wti_crude": "stooq",
    "spx_index": "stooq",
    "ndx_index": "stooq",
    "eurusd": "stooq",
    "usdjpy": "stooq",
}
_STORE_MARKET_WIDE = frozenset({
    "fear_greed", "pm_risk_on", "macro_regime", "putcall_ratio", "vix_level", "fed_funds_rate",
    "defi_tvl", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope",
    "osint_air_activity", "pm_implied_prob", "pm_prob_velocity", "pm_book_depth",
    "reddit_sentiment", "twitter_sentiment", "twitter_influencer_sentiment",
    "gdelt_tone", "reg_risk_crypto", "risk_on_off",
    "gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy",
})
# Registry name → stored metric name, for features renamed after their first ingest.
# StoreBackedAltProvider tries the registry name first; if the store returns nothing it falls back here
# so data written under the old name is still accessible until re-ingested under the canonical name.
_STORE_METRIC_ALIAS: dict[str, str] = {
    "pm_risk_on": "risk_on",
    "liquidation_cascade": "liquidations",
}


class StoreBackedAltProvider:
    """Adapts the append-only point-in-time store (AltDataStore / PgAltDataStore) into the AltDataProvider
    seam the gate consumes — so the SAME `evaluate_*` code runs on real ingested data, not just fixtures.
    Returns the full revision history (read_all); the gate's per-bar as-of join does the point-in-time
    selection, so no future revision can leak into a past bar."""

    def __init__(self, store: Any, *, provider_of: dict[str, str] | None = None, market_wide: frozenset[str] = _STORE_MARKET_WIDE) -> None:
        self._store = store
        self._provider_of = provider_of or dict(_STORE_PROVIDER_OF)
        self._market_wide = market_wide

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        provider = self._provider_of.get(metric)
        if provider is None:
            return []
        key = "MARKET" if metric in self._market_wide else symbol
        points = self._store.read_all(provider, key, metric)
        if not points:
            alias = _STORE_METRIC_ALIAS.get(metric)
            if alias:
                points = self._store.read_all(provider, key, alias)
        return points[-limit:]


class FixtureNewsProvider:
    """Deterministic offline headlines so the gate + tests run with no key/network."""

    def __init__(self, news: dict[str, list[NewsItem]]) -> None:
        self.news = news
        self.calls: list[tuple[str, int]] = []

    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        self.calls.append((symbol, limit))
        return self.news.get(symbol, [])[-limit:]


def read_pit_fee(
    store: Any,  # AltDataStore | PgAltDataStore — must have read_asof; Store (DB) is handled below
    venue_id: str,
    symbol: str,
    metric: str,  # "venue_fees_maker" | "venue_fees_taker"
    as_of: datetime,
    *,
    fallback_bps: float | None = None,
) -> float | None:
    """Read the latest PIT fee (bps) for a venue × symbol as of `as_of`.

    The store key is ``(provider="venue_fees", symbol=<venue_id>:<symbol>, metric=<metric>)``.
    If no row exists and `fallback_bps` is given, returns that.  Otherwise None.

    Accepts AltDataStore, PgAltDataStore, or the core Store (which wraps PgAltDataStore internally).
    The core Store does not have `read_asof` directly — it is wrapped transparently here so callers
    can pass whichever store they hold.

    This is the single read seam for gate.py / costopt.py / execution.py so every
    fee read is point-in-time, with NO look-ahead.
    """
    # If the caller holds a core Store (has .rows but not .read_asof), wrap it as PgAltDataStore.
    alt_store = store
    if not hasattr(store, "read_asof"):
        try:
            alt_store = PgAltDataStore(store)
        except Exception:  # noqa: BLE001
            return fallback_bps
    store_symbol = f"{venue_id}:{symbol}"
    try:
        points = alt_store.read_asof("venue_fees", store_symbol, metric, as_of)
    except Exception:  # noqa: BLE001 — never crash the order path over a fee read
        return fallback_bps
    if points:
        return points[-1].value
    return fallback_bps


class VenueFeesProvider:
    """Point-in-time venue fee snapshots via ccxt `fetchTradingFees`.

    Fetches *this account's* maker/taker schedule (already reflecting VIP tier,
    token discounts, and promos) for each symbol on a venue.  Requires an
    authenticated ccxt exchange instance; falls back down a three-rung ladder:

        1. `exchange.fetchTradingFees()` — account-specific (preferred)
        2. `exchange.describe()['fees']` — published brochure rates
        3. Static catalog values in `fallback_fees` — offline / no-key safe

    Stores two metrics per venue × symbol via `fetch_series`:
        - ``venue_fees_maker``  maker fee in bps (negative = rebate)
        - ``venue_fees_taker``  taker fee in bps

    The `available_at` timestamp equals the fetch timestamp — fees are a live
    read, not a publication-lagged series.  KEY-GATED: an absent / disabled ccxt
    client returns [] so the system degrades honestly (never fabricates a fee read).
    Offline-testable via the injected `_fetcher` callable.
    """

    # Per-venue static fallback fees (bps) used when ccxt is unavailable.
    _STATIC_FALLBACK: dict[str, tuple[float, float]] = {
        "binance": (10.0, 10.0),
        "binanceusdm": (2.0, 4.0),
        "okx": (8.0, 10.0),
        "kraken": (16.0, 26.0),
        "krakenfutures": (2.0, 5.0),
        "coinbasepro": (40.0, 60.0),
        "coinbase": (40.0, 60.0),
    }

    def __init__(
        self,
        exchange_id: str,
        ccxt_exchange=None,  # a live authenticated ccxt exchange instance or None
        fallback_fees: dict[str, tuple[float, float]] | None = None,
        *,
        _fetcher=None,  # injectable: fn(exchange) -> dict mapping symbol -> {maker, taker}
    ) -> None:
        self.exchange_id = exchange_id.lower()
        self._exchange = ccxt_exchange
        self._fallback = fallback_fees or dict(self._STATIC_FALLBACK)
        self._fetcher = _fetcher

    # ------------------------------------------------------------------
    # Public AltDataProvider seam
    # ------------------------------------------------------------------

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        """Fetch one fee metric for one symbol.  `metric` is one of
        ``venue_fees_maker`` or ``venue_fees_taker``.  Returns a list with a
        single point stamped now (the snapshot is a current read, not a history).
        Returns [] when metric is unknown or fees cannot be fetched."""
        if metric not in ("venue_fees_maker", "venue_fees_taker"):
            return []
        kind = "maker" if metric == "venue_fees_maker" else "taker"
        bps = self._fee_bps(symbol, kind)
        if bps is None:
            return []
        now = datetime.now(tz=UTC)
        return [AltDataPoint(ts=now, available_at=now, value=bps)]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fee_bps(self, symbol: str, kind: str) -> float | None:
        """Return the fee in basis points for this symbol and kind (maker/taker),
        walking the fallback ladder.  Returns None only when no info at all."""
        # Rung 1: injected fetcher (used by tests and live authenticated path)
        if self._fetcher is not None:
            fees = self._fetcher(self._exchange)
            if fees and symbol in fees:
                return float(fees[symbol].get(kind, fees[symbol].get("taker", 0))) * 10000.0
            # injected fetcher present but symbol missing → try describe/static
        elif self._exchange is not None:
            fees = self._ccxt_fetch_fees()
            if fees and symbol in fees:
                entry = fees[symbol]
                return float(entry.get(kind, entry.get("taker", 0))) * 10000.0
            # symbol not in response → fall through

        # Rung 2: ccxt exchange.describe()['fees']
        if self._exchange is not None:
            bps = self._describe_fee(kind)
            if bps is not None:
                return bps

        # Rung 3: static catalog
        pair = self._fallback.get(self.exchange_id)
        if pair is not None:
            return pair[0] if kind == "maker" else pair[1]

        return None  # no info available — caller returns []

    def _ccxt_fetch_fees(self) -> dict | None:
        """Call ccxt `fetchTradingFees`; return None on any failure (rate-limit, auth error, etc.)."""
        try:
            result = self._exchange.fetchTradingFees()
            return result if isinstance(result, dict) else None
        except Exception:  # noqa: BLE001 — one dead source never aborts the pass
            return None

    def _describe_fee(self, kind: str) -> float | None:
        """Extract a fee (bps) from ccxt's `describe()['fees']`.  Returns None if absent."""
        try:
            desc = self._exchange.describe()
            fees = (desc.get("fees") or {}).get("trading") or {}
            rate = fees.get(f"{kind}Fee") or fees.get("taker" if kind == "taker" else "maker")
            if rate is not None:
                return float(rate) * 10000.0
        except Exception:  # noqa: BLE001
            pass
        return None


def rolling_zscore(values: list[float | None], lookback: int) -> list[float | None]:
    """Causal z-score: only past+current values, never the full sample (a full-sample z is lookahead)."""
    out: list[float | None] = [None] * len(values)
    window: list[float] = []
    for idx, value in enumerate(values):
        if value is None:
            window = []
            continue
        window.append(value)
        if len(window) > lookback:
            window.pop(0)
        if len(window) >= max(2, lookback):
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            sd = math.sqrt(var)
            out[idx] = (value - mean) / sd if sd else 0.0
    return out
