# intent: FREE, no-key, point-in-time daily price sources spanning asset classes (equity indexes, FX, metals,
# commodities) so the cross-asset lab has real non-crypto reads; inputs: Stooq daily CSV (primary) or Yahoo
# chart JSON (drop-in alternate), both free + keyless; outputs: AltDataPoint close series under the SEMANTIC
# market-wide metric names (gold_xau / silver_xag / wti_crude / spx_index / ndx_index / eurusd / usdjpy);
# invariants: every point is point-in-time (a daily close is finalized AFTER the session, so available_at =
# ts + 1 day — a conservative floor, never look-ahead), an unknown metric / failure / empty response → []
# (honest 'no data', never a fabricated read), NO API key required, NO LLM, offline-testable via an injected
# `_fetcher`. Bar (OHLCV) history for the SAME free sources lives in ingest/bars.py and reuses the Stooq
# helpers here (parse once, no duplication).

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataPoint

# Frozen, versioned transform — pinned into any feature built from these sources so a gate-passed survivor
# stays re-runnable byte-for-byte. Bump if the parse/availability convention changes.
TRANSFORM_VERSION = "multiasset-daily-v1"

# A daily close is only finalized once the session ends, so we'd have known it the NEXT day — a conservative
# point-in-time floor (mirrors FRED / CBOE / DeFiLlama daily availability). Never look-ahead.
_AVAILABILITY_LAG = timedelta(days=1)

# The market-wide cross-asset price features this module serves, mapped to each provider's native ticker.
# One free provider covers metals, commodities, equity indexes, and FX — breadth without a key.
# (DXY is intentionally absent: it is already served by FRED's DTWEXBGS — no duplicate route.)
_STOOQ_SYMBOL: dict[str, str] = {
    "gold_xau": "xauusd",   # spot gold / USD (metals)
    "silver_xag": "xagusd",  # spot silver / USD (metals)
    "wti_crude": "cl.f",    # WTI crude front-month (commodity / macro)
    "spx_index": "^spx",    # S&P 500 index (equity index)
    "ndx_index": "^ndx",    # Nasdaq-100 index (equity index)
    "eurusd": "eurusd",     # EUR/USD (FX)
    "usdjpy": "usdjpy",     # USD/JPY (FX)
}
_YAHOO_SYMBOL: dict[str, str] = {
    "gold_xau": "GC=F",
    "silver_xag": "SI=F",
    "wti_crude": "CL=F",
    "spx_index": "^GSPC",
    "ndx_index": "^NDX",
    "eurusd": "EURUSD=X",
    "usdjpy": "JPY=X",
}

# The metric set this module owns (the SEMANTIC names; both providers serve all of them).
MULTIASSET_METRICS: tuple[str, ...] = tuple(_STOOQ_SYMBOL)


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed context so HTTPS works on hosts without system CA certs (sandbox, slim images)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# --------------------------------------------------------------------------- Stooq (primary, CSV, no key)


def stooq_daily_url(ticker: str) -> str:
    """The free Stooq daily-history CSV endpoint for a native ticker (no key)."""
    return f"https://stooq.com/q/d/l/?{urllib.parse.urlencode({'s': ticker, 'i': 'd'})}"


def parse_stooq_csv(text: str) -> list[dict[str, float | datetime]]:
    """Parse a Stooq daily CSV (`Date,Open,High,Low,Close,Volume`) into ascending OHLCV rows. A non-date or
    short/`N/D` line is skipped (Stooq emits `No data` text on a bad ticker → [] honestly). Shared by the
    close-only provider here and the OHLCV bar backfiller in ingest/bars.py — one parser, no duplication."""
    out: list[dict[str, float | datetime]] = []
    for line in text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 5:
            continue
        ts = _parse_date(cols[0])
        if ts is None:
            continue  # header / preamble / "No data" line
        try:
            o, h, low, c = float(cols[1]), float(cols[2]), float(cols[3]), float(cols[4])
            v = float(cols[5]) if len(cols) > 5 and cols[5] not in ("", "N/D") else 0.0
        except ValueError:
            continue
        out.append({"ts": ts, "open": o, "high": h, "low": low, "close": c, "volume": v})
    out.sort(key=lambda r: r["ts"])  # type: ignore[arg-type,return-value]
    return out


def _parse_date(raw: str) -> datetime | None:
    """Stooq dates are YYYY-MM-DD; return None for non-date cells (the `Date` header / error text)."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


class StooqDailyProvider:
    """Free, keyless daily close series for cross-asset price levels (metals / commodities / equity indexes /
    FX) via Stooq's public CSV. Market-wide: `symbol` is ignored; `metric` selects the native ticker. The
    close for a session is finalized after the close, so each point is stamped available the NEXT day — a
    conservative point-in-time floor, never look-ahead. Unknown metric / failure / empty → [] (honest).
    Offline-testable via an injected `_fetcher(url) -> str` (canned CSV; no live network in tests)."""

    def __init__(self, *, _fetcher: Callable[[str], str] | None = None) -> None:
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
            return resp.read().decode("utf-8")

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        ticker = _STOOQ_SYMBOL.get(metric)
        if ticker is None:
            return []
        rows = parse_stooq_csv(self._fetcher(stooq_daily_url(ticker)))
        out = [AltDataPoint(ts=r["ts"], available_at=r["ts"] + _AVAILABILITY_LAG, value=float(r["close"])) for r in rows]  # type: ignore[operator,arg-type]
        return out[-limit:] if limit and len(out) > limit else out


# --------------------------------------------------------------------------- Yahoo (alternate, JSON, no key)


class YahooDailyProvider:
    """Drop-in FREE alternate for `StooqDailyProvider` over Yahoo's public chart JSON (no key). Same metric
    contract + same point-in-time availability (next-day floor), so an operator can swap it in if Stooq is
    unreachable: `Providers(multiasset=YahooDailyProvider())`. Unknown metric / failure / empty → [] (honest).
    Offline-testable via an injected `_fetcher(url) -> dict`."""

    def __init__(self, *, range_: str = "2y", _fetcher: Callable[[str], dict] | None = None) -> None:
        self.range_ = range_
        self._fetcher = _fetcher or self._fetch

    def _fetch(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:  # noqa: S310 — fixed host
            return json.loads(resp.read().decode("utf-8"))

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]:
        ticker = _YAHOO_SYMBOL.get(metric)
        if ticker is None:
            return []
        query = urllib.parse.urlencode({"interval": "1d", "range": self.range_})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?{query}"
        payload = self._fetcher(url)
        out = _points_from_yahoo(payload)
        return out[-limit:] if limit and len(out) > limit else out


def _points_from_yahoo(payload: dict) -> list[AltDataPoint]:
    """Yahoo chart JSON: result[0].timestamp[] paired with indicators.quote[0].close[]. A null close (Yahoo
    pads gaps with null) is skipped. available_at = ts + 1 day (close finalized after the session)."""
    try:
        result = (payload.get("chart", {}).get("result") or [])[0]
        stamps = result.get("timestamp") or []
        closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    except (IndexError, AttributeError, TypeError):
        return []
    out: list[AltDataPoint] = []
    for stamp, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        ts = datetime.fromtimestamp(int(stamp), tz=UTC)
        out.append(AltDataPoint(ts=ts, available_at=ts + _AVAILABILITY_LAG, value=float(close)))
    return sorted(out, key=lambda p: p.ts)
