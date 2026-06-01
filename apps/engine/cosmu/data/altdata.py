# intent: a point-in-time-safe seam for social/alt data (LunarCrush etc.) feeding the gate and, later, the LLM feature factory; inputs: provider pulls; outputs: ordered AltDataPoint series readable "as of" a time; invariants: every point carries an availability time, snapshots are append-only (vendors revise history — we never overwrite), transforms are causal (rolling only), and secrets stay server-side.

from __future__ import annotations

import json
import math
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


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


class LunarCrushProvider:
    """LunarCrush social metrics over HTTP (stdlib, no extra dep). Key is server-side only.
    Availability time defaults to one bar after observation (you learn a day's social data after it closes)."""

    def __init__(self, api_key: str, base_url: str = "https://lunarcrush.com/api4/public") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode({"bucket": "day"})
        url = f"{self.base_url}/coins/{coin}/time-series/v2?{query}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in payload.get("data", [])[-limit:]:
            if metric not in row:
                continue
            ts = datetime.fromtimestamp(int(row["time"]), tz=UTC)
            available = datetime.fromtimestamp(int(row["time"]) + 86400, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=available, value=float(row[metric])))
        return out


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


class FixtureNewsProvider:
    """Deterministic offline headlines so the gate + tests run with no key/network."""

    def __init__(self, news: dict[str, list[NewsItem]]) -> None:
        self.news = news
        self.calls: list[tuple[str, int]] = []

    def fetch_news(self, symbol: str, *, limit: int) -> list[NewsItem]:
        self.calls.append((symbol, limit))
        return self.news.get(symbol, [])[-limit:]


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
