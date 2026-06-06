from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from ._types import AltDataPoint, _ssl_context


class LunarCrushProvider:
    """LunarCrush v4 social metrics over HTTP (stdlib, no extra dep). KEY-GATED: the key is server-side only,
    and with NO key the provider returns [] so the system degrades honestly (it never fabricates a social read).
    Our semantic metric names map to the LunarCrush v4 coin time-series fields (`_FIELD`). Availability defaults
    to one bar after observation (a day's social data is known only after the day closes — point-in-time, no
    look-ahead). Low-confidence/tier1 until it earns its place out-of-sample."""

    # semantic metric (feature_registry name) -> LunarCrush v4 coin time-series field. Mirrors ALL twelve fields
    # scripts/lunarcrush_max_extract.py (_COIN_FIELDS) hoards per coin, so the scheduled live provider and the
    # bulk grab fetch + name the same series. NB: social_volume maps to the v4 `interactions` field (the bulk
    # grab's source of truth); `social_volume` is also accepted for backward-compat with the older fixture shape
    # that exposed it directly. price_usd maps to the v4 `close` field (the grab script's FIX: the price column
    # is `close`, not `price`, which had stored 0 rows); `price` is kept as a back-compat fallback below.
    _FIELD = {
        "social_volume": "interactions",
        "social_sentiment": "sentiment",
        "galaxy_score": "galaxy_score",
        "alt_rank": "alt_rank",
        "social_dominance": "social_dominance",
        "market_dominance": "market_dominance",
        "contributors_active": "contributors_active",
        "posts_active": "posts_active",
        "spam": "spam",
        "market_cap_usd": "market_cap",
        "volume_24h_usd": "volume_24h",
        "price_usd": "close",
    }
    # Older v4 field names kept as fallbacks so historical fixtures/responses still resolve: social_volume's
    # legacy `social_volume` column, and price_usd's legacy `price` column (superseded by `close`).
    _FIELD_FALLBACK = {"social_volume": "social_volume", "price_usd": "price"}

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
        fallback = self._FIELD_FALLBACK.get(metric)
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        query = urllib.parse.urlencode({"bucket": "day"})
        url = f"{self.base_url}/coins/{coin}/time-series/v2?{query}"
        payload = self._fetcher(url)
        out: list[AltDataPoint] = []
        for row in payload.get("data", [])[-limit:]:
            raw = row.get(field)
            if raw is None and fallback is not None:
                raw = row.get(fallback)  # older v4 field name (e.g. social_volume) for back-compat
            if raw is None:
                continue
            ts = datetime.fromtimestamp(int(row["time"]), tz=UTC)
            available = datetime.fromtimestamp(int(row["time"]) + 86400, tz=UTC)
            out.append(AltDataPoint(ts=ts, available_at=available, value=float(raw)))
        return out
