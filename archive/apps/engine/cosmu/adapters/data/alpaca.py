# intent: the Alpaca equities DATA lane — a MarketDataProvider over the Alpaca market-data REST API (IEX feed,
# free with any Alpaca account) plus the core.DataAdapter wrapper; inputs: settings-resolved keys (paper keys
# authenticate the data API too) + symbol/timeframe; outputs: CLOSED, split+dividend-ADJUSTED daily bars, cached
# to disk; invariants: key-gated (no keys → [] / from_settings None — honest degradation, never fabricated bars;
# the equity lane stays on the keyless Yahoo/Stooq path), the in-progress daily bar is DROPPED before caching
# (the closed-candle guard the keyless equity providers lack), a stale cache is refetched (never served forever),
# `adjustment=all` bars carry dividends so equity marks are total-return-honest, and the fetch layer is
# injectable so tests run on canned JSON (no network).

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.core.interfaces import AssetClass
from cosmu.core.interfaces import Bar as CoreBar
from cosmu.core.interfaces import Feature, Instrument
from cosmu.data.market import (
    Bar,
    _atomic_write_text,
    _bar_from_json,
    _bars_to_rows,
    _cache_is_fresh,
    _drop_unclosed,
    _merge_bars,
)

DATA_BASE_URL = "https://data.alpaca.markets"
_TIMEOUT_S = 20
# IEX is the free feed every Alpaca account gets; SIP needs a paid market-data subscription.
_FEED = "iex"


def _parse_bars(payload: dict) -> list[Bar]:
    """Alpaca GET /v2/stocks/{symbol}/bars rows → Bars. Pure (offline-testable). Timestamps are ISO-8601 UTC;
    `adjustment=all` means closes already carry splits AND dividends (total-return honest)."""
    out: list[Bar] = []
    for row in payload.get("bars") or []:
        try:
            ts = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
            out.append(
                Bar(
                    ts=ts if ts.tzinfo else ts.replace(tzinfo=UTC),
                    open=Decimal(str(row["o"])),
                    high=Decimal(str(row["h"])),
                    low=Decimal(str(row["l"])),
                    close=Decimal(str(row["c"])),
                    volume=Decimal(str(row.get("v", 0))),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue  # one malformed row is skipped, never fabricated
    return sorted(out, key=lambda b: b.ts)


class AlpacaDailyBarsProvider:
    """MarketDataProvider for Alpaca daily equity bars (IEX feed, adjustment=all). Key-gated: build via
    .from_settings(...) which returns None without keys, so callers fall back to the keyless Yahoo/Stooq path.
    Unlike those providers this one has BOTH equity-lane safeguards the deep review flagged as missing:
    the in-progress day bar is dropped (closed-candle guard) and a stale cache is refetched."""

    def __init__(
        self,
        cache_dir: Path | str = ".cosmu/alpaca_bars",
        *,
        fetcher: Callable[[str, int], dict] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._fetcher = fetcher  # (symbol, limit) -> raw payload dict; tests inject canned JSON
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    @classmethod
    def from_settings(cls, settings: Settings, cache_dir: Path | str = ".cosmu/alpaca_bars") -> AlpacaDailyBarsProvider | None:
        """None without keys — the honest degradation seam (callers keep the keyless equity provider)."""
        key = settings.alpaca_paper_api_key or settings.alpaca_api_key
        secret = settings.alpaca_paper_api_secret or settings.alpaca_api_secret
        if not key or not secret:
            return None
        return cls(cache_dir, fetcher=_urllib_fetcher(key, secret))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        if timeframe != "1d" or self._fetcher is None:
            return []  # daily-only lane; no fetcher (no keys) → honest empty, caller falls back
        now = self._now_fn()
        cached = self._read_cache(symbol)
        if len(cached) >= limit and _cache_is_fresh(cached, timeframe, now):
            return cached[-limit:]
        try:
            payload = self._fetcher(symbol, max(limit + 5, 60))
        except Exception:  # noqa: BLE001 — offline/rate-limited: degrade to whatever the cache holds
            return cached[-limit:]
        bars = _drop_unclosed(_parse_bars(payload), timeframe, now)
        if not bars:
            return cached[-limit:]
        merged = _merge_bars(cached, bars)
        _atomic_write_text(self._cache_path(symbol), json.dumps(_bars_to_rows(merged), separators=(",", ":")))
        return merged[-limit:]

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.upper()}_1d.json"

    def _read_cache(self, symbol: str) -> list[Bar]:
        path = self._cache_path(symbol)
        if not path.exists():
            return []
        try:
            return [_bar_from_json(r) for r in json.loads(path.read_text())]
        except (ValueError, KeyError, TypeError):
            return []


def _urllib_fetcher(api_key: str, api_secret: str) -> Callable[[str, int], dict]:
    """The real HTTP fetcher. Credentials live ONLY in this closure — never on the provider instance."""

    def _fetch(symbol: str, limit: int) -> dict:
        start = (datetime.now(tz=UTC) - timedelta(days=int(limit * 1.6) + 10)).date().isoformat()
        query = urllib.parse.urlencode(
            {"timeframe": "1Day", "adjustment": "all", "feed": _FEED, "limit": str(limit), "start": start}
        )
        url = f"{DATA_BASE_URL}/v2/stocks/{urllib.parse.quote(symbol)}/bars?{query}"
        req = urllib.request.Request(  # noqa: S310 — fixed https base url
            url, headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            return json.loads(resp.read().decode())

    return _fetch


class AlpacaDataAdapter:
    """core.DataAdapter for Alpaca US equities. Universe = the catalog's alpaca instruments (real listings,
    never invented); bars via AlpacaDailyBarsProvider; features none (equities alt-features flow through the
    ingest registry, not this adapter). Without keys every read is honestly empty — same contract as the
    IBKR stub, but this one turns ON the moment ALPACA_PAPER_API_KEY/SECRET land in the env."""

    asset_class = AssetClass.EQUITY
    survivorship_complete = False  # the catalog lists current instruments only; no delisted history

    def __init__(self, provider: AlpacaDailyBarsProvider | None) -> None:
        self._provider = provider

    @classmethod
    def from_settings(cls, settings: Settings) -> AlpacaDataAdapter:
        return cls(AlpacaDailyBarsProvider.from_settings(settings))

    def universe(self, as_of: datetime) -> list[Instrument]:
        if self._provider is None:
            return []
        from cosmu.spine.venue import default_catalog

        return [
            Instrument(
                id=i.id, symbol=i.symbol, asset_class=AssetClass.EQUITY, venue=i.venue_id,
                tick_size=i.tick_size, lot_size=i.lot_size, min_notional=i.min_notional, quote_ccy="USD",
            )
            for i in default_catalog().instruments
            if i.venue_id == "alpaca"
        ]

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[CoreBar]:
        if self._provider is None:
            return []
        symbol = instrument_id.split("-")[0].upper() if "-" in instrument_id else instrument_id
        span_days = max(1, int((end - start).total_seconds() // 86400) + 2)
        raw = self._provider.fetch_bars(symbol, "1d", limit=min(span_days, 1000))
        out: list[CoreBar] = []
        for b in raw:
            if not (start <= b.ts <= end):
                continue
            out.append(
                CoreBar(
                    instrument_id=instrument_id, ts=b.ts, interval=interval, open=b.open, high=b.high,
                    low=b.low, close=b.close, volume=b.volume,
                    # PIT honesty: a daily bar is knowable only after its session closes; stamping the next
                    # UTC midnight is conservative for any intra-session reader.
                    available_at=b.ts + timedelta(days=1),
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        return []
