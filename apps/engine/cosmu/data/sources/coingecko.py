# intent: CoinGecko — a FREE (no-key, public tier), per-coin point-in-time DataSource for the crypto lens.
# Two surfaces on https://api.coingecko.com (free public tier, no API key):
#   PER-COIN daily series via /coins/{id}/market_chart  (market cap + total volume time series):
#     cg_market_cap   — the coin's market cap (USD)
#     cg_total_volume — the coin's 24h total traded volume (USD)
#   MARKET-WIDE via /global  (BTC dominance % of total crypto mcap):
#     cg_btc_dominance — BTC's share of total crypto market cap (a risk-rotation gauge)
#
# This adapter satisfies the DataSource protocol (registry.py) so any agent can discover + PIT-query it by
# name. It mirrors the house pattern (see wikipedia_pageviews.py / multiasset.py / defillama.py):
#   - inject `_fetcher(url) -> dict` so the ENTIRE HTTP path is mockable (deterministic offline tests)
#   - a network / shape failure degrades to a None-valued SourceFeature, NEVER raises (never aborts a pass)
#   - gaps are ABSENT AltDataPoints, NEVER zero-fabricated
#   - an unknown symbol returns a None-valued SourceFeature (never crashes the gate pass)
#
# PIT contract (the machine that never lies):
#   For the daily series, available_at = ts + 1 day. CoinGecko's market_chart at `interval=daily` stamps a
#   day-T bucket, and a daily aggregate is only finalized after the day closes — the EARLIEST day-T is
#   knowable is day T+1 (00:00 UTC). A conservative floor, never look-ahead. (Same convention as
#   FRED / multiasset / DefiLlama daily.) BTC dominance from /global is a CURRENT snapshot, so its
#   available_at is the fetch time (we only knew it when we pulled it) — honest, never back-dated.
#   revisions    = CoinGecko may re-state very recent days; we stamp the conservative +1d floor and surface
#                  revisions through the store's append-only contract, never hide them.
#
# Note: this is the NEWER named-DataSource seam that the registry discovers. It is per-coin (+ one market-wide
# dominance read), distinct from the legacy market-wide providers. Additive, no regressions.

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cosmu.data.providers._types import AltDataPoint, _ssl_context
from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned transform version — bump if the parse / availability convention changes so a gate-passed survivor
# stays re-runnable byte-for-byte.
TRANSFORM_VERSION = "coingecko-daily-v1"

# A daily aggregate is finalized after the day closes, so we'd have known it the NEXT day — a conservative
# point-in-time floor (mirrors FRED / multiasset / DefiLlama daily). Never look-ahead.
_AVAILABILITY_LAG = timedelta(days=1)

# Free, no-key CoinGecko public API.
_API_BASE = "https://api.coingecko.com/api/v3"
_GLOBAL_URL = f"{_API_BASE}/global"

# How many trailing days of daily history to request per market_chart call.
_DEFAULT_LOOKBACK_DAYS = 90

# The metrics this module owns. Each maps to a parser; cg_btc_dominance is the lone market-wide read.
COINGECKO_METRICS: tuple[str, ...] = ("cg_market_cap", "cg_total_volume", "cg_btc_dominance")
_MARKET_WIDE_METRICS: frozenset[str] = frozenset({"cg_btc_dominance"})

# market_chart response key for each per-coin metric.
_CHART_KEY: dict[str, str] = {
    "cg_market_cap": "market_caps",
    "cg_total_volume": "total_volumes",
}

# Per-metric declared priors — why an agent might care (low-confidence until OOS proves it).
_PRIORS: dict[str, str] = {
    "cg_market_cap": (
        "A coin's market cap is its float-weighted size; large relative moves track capital rotating in/out "
        "of the asset. Daily, free, knowable day T+1. Low-confidence until validated OOS."
    ),
    "cg_total_volume": (
        "24h total traded volume proxies attention / conviction; a volume spike often accompanies the onset "
        "of a move. Daily, free, knowable day T+1. Low-confidence until validated OOS."
    ),
    "cg_btc_dominance": (
        "BTC dominance (BTC's share of total crypto mcap) is a risk-rotation gauge: falling dominance is "
        "capital rotating into alts (risk-on within crypto), rising dominance is a flight to BTC. A current "
        "snapshot from /global. Low-confidence until validated OOS."
    ),
}

# Canonical symbol → CoinGecko coin id map (case-sensitive ids as CoinGecko uses them). None = disabled for
# that symbol (returns None gracefully). Extend this map to add coins without touching the adapter logic.
COIN_ID_MAP: dict[str, str | None] = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
    "XRPUSDT": "ripple",
    "DOGEUSDT": "dogecoin",
    "ADAUSDT": "cardano",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "DOTUSDT": "polkadot",
    "MATICUSDT": "matic-network",
    "LTCUSDT": "litecoin",
    "ATOMUSDT": "cosmos",
    "NEARUSDT": "near",
    "FTMUSDT": "fantom",
    "BTC": "bitcoin",
    "ETH": "ethereum",
}

# Base-asset fallback: strip a quote-currency suffix and retry on the common base ticker.
_BASE_ASSET_FALLBACK: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
    "FTM": "fantom",
}


def _coin_id_for_symbol(symbol: str) -> str | None:
    """Resolve symbol → CoinGecko coin id. Returns None if the source is disabled for this symbol."""
    if symbol in COIN_ID_MAP:
        return COIN_ID_MAP[symbol]
    for suffix in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
        if symbol.endswith(suffix):
            base = symbol[: -len(suffix)]
            if base in _BASE_ASSET_FALLBACK:
                return _BASE_ASSET_FALLBACK[base]
    return None  # unknown; caller returns None gracefully


def _market_chart_url(coin_id: str, days: int) -> str:
    """CoinGecko market_chart URL for one coin over a daily window (free, no key)."""
    query = urllib.parse.urlencode({"vs_currency": "usd", "days": days, "interval": "daily"})
    return f"{_API_BASE}/coins/{urllib.parse.quote(coin_id)}/market_chart?{query}"


def _parse_market_chart(payload: Any, chart_key: str) -> list[AltDataPoint]:
    """Parse a market_chart response: {"<chart_key>": [[ts_ms, value], ...], ...}.

    PIT: available_at = ts + 1 day. A null / non-finite / non-positive value is ABSENT (never zero-filled).
    The bucket ts (ms) is normalised to midnight UTC of its day so available_at lands on the next day."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get(chart_key) or []
    out: list[AltDataPoint] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        raw_ts, raw_val = row[0], row[1]
        if raw_val is None:
            continue
        try:
            # market_chart timestamps are ms; normalise to the day's midnight UTC.
            day = datetime.fromtimestamp(int(raw_ts) / 1000, tz=UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            value = float(raw_val)
        except (ValueError, TypeError, OSError):
            continue
        if value <= 0:
            continue  # missing / not-yet-aggregated → absent, not zero
        out.append(AltDataPoint(ts=day, available_at=day + _AVAILABILITY_LAG, value=value))
    return sorted(out, key=lambda p: p.ts)


def _parse_btc_dominance(payload: Any, fetch_at: datetime) -> list[AltDataPoint]:
    """Parse /global: {"data": {"market_cap_percentage": {"btc": <pct>, ...}}}.

    This is a CURRENT snapshot — available_at = fetch_at (we only knew it when we pulled it). A single point."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    pct = (data.get("market_cap_percentage") or {})
    raw = pct.get("btc") if isinstance(pct, dict) else None
    if raw is None:
        return []
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return []
    if value <= 0:
        return []
    return [AltDataPoint(ts=fetch_at, available_at=fetch_at, value=value)]


class CoinGeckoSource:
    """CoinGecko market data as a named, point-in-time DataSource (free public tier, no key).

    Metrics (selected by the `metric` kwarg):
      cg_market_cap    — PER-COIN daily market cap (USD)
      cg_total_volume  — PER-COIN daily 24h total volume (USD)
      cg_btc_dominance — MARKET-WIDE BTC dominance %, current snapshot from /global

    PIT contract: the per-coin daily series uses available_at = ts + 1 day (a daily aggregate is finalized
    after the day closes). BTC dominance is a current snapshot stamped available_at = fetch time. Gaps are
    absent AltDataPoints (never zero-fabricated). A network / shape failure or unknown symbol returns a
    None-valued SourceFeature — NEVER raises, NEVER fabricates.

    Offline testability: inject `_fetcher(url) -> dict` in the constructor. All HTTP is isolated behind that
    single callable, so tests are fully deterministic with no network and no key."""

    name: str = "cg_market_cap"
    kind: SourceKind = "price"
    metric: str = "cg_market_cap"
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.45  # tier1 / low-confidence — must earn its place via OOS

    def __init__(
        self,
        *,
        metric: str = "cg_market_cap",
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        _fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        if metric not in COINGECKO_METRICS:
            raise ValueError(f"unknown CoinGecko metric {metric!r}; expected one of {COINGECKO_METRICS}")
        self.metric = metric
        self.name = metric  # the metric IS the discoverable feature name (consistent with feature_registry)
        self.lookback_days = lookback_days
        self.prior = _PRIORS[metric]
        self.market_wide = metric in _MARKET_WIDE_METRICS
        self.kind = "macro" if self.market_wide else "price"
        self._fetcher: Callable[[str], Any] = _fetcher or self._live_fetch

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def _live_fetch(self, url: str) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1 (contact.moncory@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
            return json.loads(resp.read().decode("utf-8"))

    def fetch_raw_series(self, symbol: str, as_of: datetime, *, limit: int = 4096) -> list[AltDataPoint]:
        """Fetch the raw AltDataPoints for `symbol` whose available_at <= as_of (strict point-in-time).

        A gap is ABSENT from the returned list — never zero-fabricated. Returns [] on any failure or for
        an unknown symbol (per-coin metrics only — dominance ignores symbol)."""
        if self.market_wide:
            try:
                payload = self._fetcher(_GLOBAL_URL)
            except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash
                return []
            pts = _parse_btc_dominance(payload, as_of)
        else:
            coin_id = _coin_id_for_symbol(symbol)
            if coin_id is None:
                return []
            try:
                payload = self._fetcher(_market_chart_url(coin_id, self.lookback_days))
            except Exception:  # noqa: BLE001 — network / 404 → absent series, never crash
                return []
            pts = _parse_market_chart(payload, _CHART_KEY[self.metric])

        pts = [p for p in pts if p.available_at <= as_of]
        return pts[-limit:] if limit and len(pts) > limit else pts

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest value for `scope` whose available_at <= as_of (point-in-time, no look-ahead).

        Returns a None-valued SourceFeature if the symbol is unknown, the API is unreachable, or nothing
        is knowable yet — NEVER raises, NEVER fabricates."""
        raw = self.fetch_raw_series(scope, as_of, limit=limit)
        latest: AltDataPoint | None = raw[-1] if raw else None
        return SourceFeature(
            name=self.name,
            scope="MARKET" if self.market_wide else scope,
            as_of=as_of,
            value=float(latest.value) if latest else None,
            available_at=latest.available_at if latest else None,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )


def make_coingecko_sources() -> list[CoinGeckoSource]:
    """Build one CoinGeckoSource per owned metric — the convenience seam the registry registers."""
    return [CoinGeckoSource(metric=m) for m in COINGECKO_METRICS]


__all__ = [
    "COINGECKO_METRICS",
    "COIN_ID_MAP",
    "TRANSFORM_VERSION",
    "CoinGeckoSource",
    "_coin_id_for_symbol",
    "_parse_btc_dominance",
    "_parse_market_chart",
    "make_coingecko_sources",
]
