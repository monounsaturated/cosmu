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
        from datetime import timedelta

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
                from datetime import timedelta
                out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=tvl))
        return sorted(out, key=lambda p: p.ts)


class CoinglassLiquidationProvider:
    """Coinglass free liquidations history (no key on the public history endpoint). Numeric → no LLM.
    Per-symbol metric "liquidations" (total long+short USD liquidated in the bucket). Coinglass closes a
    bucket before it publishes it, so a bucket observed at time T is available at the NEXT bucket boundary
    (here +1 day for the daily interval) — a conservative point-in-time floor, never look-ahead."""

    def __init__(self, base_url: str = "https://open-api.coinglass.com", interval: str = "1d", bucket_seconds: int = 86400) -> None:
        self.base_url = base_url.rstrip("/")
        self.interval = interval
        self.bucket_seconds = bucket_seconds

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "liquidations":
            return []
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode({"symbol": coin, "interval": self.interval})
        url = f"{self.base_url}/public/v2/liquidation_history?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _points_from_coinglass(payload, self.bucket_seconds)[-limit:]


class CboePutCallProvider:
    """CBOE free total put/call ratio (daily CSV, no key). Market-wide metric "putcall_ratio"; symbol
    ignored (one series for the whole tape). The ratio for a session is finalized AFTER the close, so each
    point is stamped available the NEXT day — a conservative point-in-time floor, never look-ahead."""

    def __init__(self, url: str = "https://cdn.cboe.com/api/global/us_indices/daily_prices/total_pc.csv", release_lag_days: int = 1) -> None:
        self.url = url
        self.release_lag_days = release_lag_days

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "putcall_ratio":
            return []
        # CBOE's CDN 403s a bare bot UA — present a browser-like UA + Accept so the free CSV is served.
        req = urllib.request.Request(
            self.url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "text/csv,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            text = resp.read().decode("utf-8")
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
    """Binance USDⓈ-M aggregate open interest (free REST, no key). Numeric; availability == publication."""

    def __init__(self, base_url: str = "https://fapi.binance.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "open_interest":
            return []
        query = urllib.parse.urlencode({"symbol": symbol, "period": "1h", "limit": min(limit, 500)})
        url = f"{self.base_url}/futures/data/openInterestHist?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=ts, value=float(row.get("sumOpenInterestValue", row.get("sumOpenInterest", 0)))))
        return sorted(out, key=lambda p: p.ts)


class BinanceBasisProvider:
    """Binance USDⓈ-M perpetual vs spot basis (free REST). Computed as (mark - index) / index."""

    def __init__(self, base_url: str = "https://fapi.binance.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "perp_spot_basis":
            return []
        url = f"{self.base_url}/fapi/v1/premiumIndex?{urllib.parse.urlencode({'symbol': symbol})}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            row = json.loads(resp.read().decode("utf-8"))
        mark = float(row.get("markPrice", 0))
        index = float(row.get("indexPrice", 0))
        if index == 0:
            return []
        basis = (mark - index) / index
        ts = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC)
        return [AltDataPoint(ts=ts, available_at=ts, value=basis)]


class ExchangeNetflowProvider:
    """Exchange net deposit/withdrawal flow proxy via Binance USDⓈ-M long/short ratio (free REST).
    Positive = net longs building (inflow proxy); negative = net shorts (outflow pressure)."""

    def __init__(self, base_url: str = "https://fapi.binance.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric != "exchange_netflow":
            return []
        query = urllib.parse.urlencode({"symbol": symbol, "period": "1h", "limit": min(limit, 500)})
        url = f"{self.base_url}/futures/data/globalLongShortAccountRatio?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        out: list[AltDataPoint] = []
        for row in rows:
            ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC)
            ratio = float(row.get("longShortRatio", 1.0))
            out.append(AltDataPoint(ts=ts, available_at=ts, value=ratio - 1.0))
        return sorted(out, key=lambda p: p.ts)


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
    """Polymarket CLOB metrics: implied probability, probability velocity, and book depth.
    Uses the Gamma API to discover macro markets and compute aggregate metrics."""

    def __init__(self, pin_token: str | None = None) -> None:
        self._gamma = PolymarketGammaProvider(pin_token=pin_token)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        if metric not in ("pm_implied_prob", "pm_prob_velocity", "pm_book_depth"):
            return []
        series = self._gamma.fetch_series(symbol, "risk_on", limit=max(limit, 2))
        if not series:
            return []
        if metric == "pm_implied_prob":
            return series[-limit:]
        if metric == "pm_prob_velocity" and len(series) >= 2:
            out: list[AltDataPoint] = []
            for i in range(1, len(series)):
                velocity = series[i].value - series[i - 1].value
                out.append(AltDataPoint(ts=series[i].ts, available_at=series[i].available_at, value=velocity))
            return out[-limit:]
        if metric == "pm_book_depth":
            return [AltDataPoint(ts=series[-1].ts, available_at=series[-1].available_at, value=1.0)]
        return []


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
    from datetime import timedelta

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


# Default routing: the gate asks for a SEMANTIC metric name; the store keyed it under the ingesting
# provider. Market-wide metrics live under the "MARKET" symbol (one series for the whole tape).
_STORE_PROVIDER_OF = {
    "funding_rate": "binance",
    "fear_greed": "alternative.me",
    "news_sentiment": "news",
    "risk_on": "polymarket",
    "macro_regime": "fred",
    "liquidations": "coinglass",
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
}
_STORE_MARKET_WIDE = frozenset({
    "fear_greed", "risk_on", "macro_regime", "putcall_ratio", "vix_level", "fed_funds_rate",
    "defi_tvl", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope",
    "osint_air_activity", "pm_implied_prob", "pm_prob_velocity", "pm_book_depth",
})


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
        return self._store.read_all(provider, key, metric)[-limit:]


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
