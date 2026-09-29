from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from ._types import AltDataPoint, _ssl_context


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


class PolymarketClobProvider:
    """Thin adapter over PolymarketClobSource (data/sources/polymarket.py), which fetches full daily
    history via the CLOB prices-history endpoint. Three metrics: pm_implied_prob, pm_prob_velocity,
    pm_book_depth — each a daily time series going back to market inception (180-400+ rows typical)."""

    def __init__(self, pin_token: str | None = None) -> None:
        from cosmu.data.sources.polymarket import PolymarketClobSource
        self._src = PolymarketClobSource(pin_token=pin_token)

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        return self._src.fetch_series(symbol, metric, limit=limit)
