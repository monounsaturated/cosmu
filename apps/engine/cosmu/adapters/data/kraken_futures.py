# intent: Kraken Futures DataAdapter — wraps Kraken Futures REST API v3 behind core.DataAdapter (linear
# perps: PF_ prefix); point-in-time honest (available_at = bar close + interval); offline-testable via
# injected market_provider. Execution NOT wired — venue live_enabled=False until live interlock + 5 gates.

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument, ProductType

_VENUE = "kraken_futures"
_BASE_URL = "https://futures.kraken.com"
# resolution param → interval_seconds (Kraken Futures uses named resolutions, not multipliers)
_INTERVAL_MAP: dict[str, tuple[str, int]] = {
    "1m":  ("1m",   60),
    "5m":  ("5m",   300),
    "15m": ("15m",  900),
    "1h":  ("60m",  3600),
    "4h":  ("240m", 14400),
    "1d":  ("1d",   86400),
}
# Known tick/lot specs for the standard linear perps we wire first
_INSTRUMENT_SPECS: dict[str, tuple[Decimal, Decimal]] = {
    "PF_XBTUSD": (Decimal("0.5"),  Decimal("1")),   # (tick_size, lot_size in contracts; 1 contract ≈ $1)
    "PF_ETHUSD": (Decimal("0.05"), Decimal("1")),
    "PF_SOLUSD": (Decimal("0.01"), Decimal("1")),
}


class KrakenFuturesMarketProvider(Protocol):
    """Injectable provider — production uses the Kraken Futures REST API; tests inject a fixture."""

    def fetch_candles(self, symbol: str, resolution: str, *, from_ms: int, to_ms: int) -> list[dict]: ...


class _LiveKrakenFuturesProvider:
    """Fetches OHLCV from Kraken Futures derivatives/api/v3 using stdlib urllib — no third-party deps."""

    def fetch_candles(self, symbol: str, resolution: str, *, from_ms: int, to_ms: int) -> list[dict]:
        url = (
            f"{_BASE_URL}/derivatives/api/v3/instruments/{symbol}/candles"
            f"?resolution={resolution}&from={from_ms}&to={to_ms}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        # Response: {"candles": [{"time": <ms>, "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]}
        return payload.get("candles", [])


class KrakenFuturesDataAdapter:
    """Kraken linear perpetuals (PF_ symbols) behind core.DataAdapter. Venue: kraken_futures (live_enabled=False).

    `symbols` uses Kraken Futures format: PF_XBTUSD, PF_ETHUSD, PF_SOLUSD.
    PI_ (inverse/coin-margined) contracts are not wired — add them when the position needs coin-delta."""

    asset_class = AssetClass.CRYPTO

    def __init__(
        self,
        symbols: list[str],
        *,
        market_provider: KrakenFuturesMarketProvider | None = None,
    ) -> None:
        self._symbols = list(symbols)
        self._market = market_provider or _LiveKrakenFuturesProvider()

    def universe(self, as_of: datetime) -> list[Instrument]:
        return [
            Instrument(
                id=f"crypto:{_VENUE}:{sym}",
                symbol=sym,
                asset_class=AssetClass.CRYPTO,
                venue=_VENUE,
                tick_size=_INSTRUMENT_SPECS.get(sym, (Decimal("0.01"), Decimal("1")))[0],
                lot_size=_INSTRUMENT_SPECS.get(sym, (Decimal("0.01"), Decimal("1")))[1],
                min_notional=Decimal("1"),
                quote_ccy="USD",
                product_type=ProductType.PERP,
            )
            for sym in self._symbols
        ]

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        sym = instrument_id.rsplit(":", 1)[-1]
        resolution, step_sec = _INTERVAL_MAP.get(interval, ("1d", 86400))
        step = timedelta(seconds=step_sec)
        raw = self._market.fetch_candles(
            sym, resolution,
            from_ms=int(start.timestamp() * 1000),
            to_ms=int(end.timestamp() * 1000),
        )
        out: list[Bar] = []
        for row in raw:
            ts = datetime.fromtimestamp(row["time"] / 1000, tz=timezone.utc)
            if not (start <= ts <= end):
                continue
            out.append(
                Bar(
                    instrument_id=instrument_id,
                    ts=ts,
                    interval=interval,
                    open=Decimal(str(row["open"])),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                    volume=Decimal(str(row["volume"])),
                    available_at=ts + step,
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        return []
