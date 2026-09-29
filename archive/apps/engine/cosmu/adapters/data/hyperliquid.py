# intent: Hyperliquid DataAdapter — wraps the Hyperliquid public `/info` API behind core.DataAdapter (perps);
# point-in-time honest (available_at = bar close + interval); offline-testable via an injected market provider.
# Execution is NOT wired here — venue live_enabled=False (non-KYC on-chain DEX) until live interlock + 5 gates.
# Symbols are BARE base assets ("BTC", "ETH") — Hyperliquid's coin convention; quote is USDC-margined perps.

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument, ProductType

_VENUE = "hyperliquid"
_BASE_URL = "https://api.hyperliquid.xyz"
# cosmu bar param → (hyperliquid interval code, interval_seconds). Hyperliquid uses the same short codes.
_INTERVAL_MAP: dict[str, tuple[str, int]] = {
    "1m":  ("1m",  60),
    "5m":  ("5m",  300),
    "15m": ("15m", 900),
    "1h":  ("1h",  3600),
    "4h":  ("4h",  14400),
    "1d":  ("1d",  86400),
}


class HyperliquidMarketProvider(Protocol):
    """Injectable provider — production POSTs to the Hyperliquid `/info` endpoint; tests inject a canned
    fixture. Returns the raw candle dicts Hyperliquid emits: {"t": open_ms, "T": close_ms, "o","h","l","c","v"}."""

    def fetch_candles(self, coin: str, interval: str, *, start_ms: int, end_ms: int) -> list[dict]: ...


class _LiveHyperliquidProvider:
    """POSTs candleSnapshot to the Hyperliquid public `/info` API using stdlib urllib — no third-party deps,
    no key (public market data)."""

    def fetch_candles(self, coin: str, interval: str, *, start_ms: int, end_ms: int) -> list[dict]:
        body = json.dumps(
            {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms}}
        ).encode()
        req = urllib.request.Request(
            f"{_BASE_URL}/info", data=body, headers={"Content-Type": "application/json", "User-Agent": "cosmu/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        # candleSnapshot returns a JSON array of candle objects.
        return payload if isinstance(payload, list) else []


class HyperliquidDataAdapter:
    """Hyperliquid perp bars behind core.DataAdapter. Venue: hyperliquid (live_enabled=False).

    `symbols` are bare base assets (e.g. "BTC", "ETH") — Hyperliquid's coin convention. Everything here is a
    USDC-margined perpetual; product_type is always PERP."""

    asset_class = AssetClass.CRYPTO

    def __init__(self, symbols: list[str], *, market_provider: HyperliquidMarketProvider | None = None) -> None:
        self._symbols = list(symbols)
        self._market = market_provider or _LiveHyperliquidProvider()

    def universe(self, as_of: datetime) -> list[Instrument]:
        return [
            Instrument(
                id=f"crypto:{_VENUE}:{sym}",
                symbol=sym,
                asset_class=AssetClass.CRYPTO,
                venue=_VENUE,
                tick_size=Decimal("1") if sym == "BTC" else Decimal("0.01"),
                lot_size=Decimal("0.0001"),
                min_notional=Decimal("1"),
                quote_ccy="USDC",
                product_type=ProductType.PERP,
            )
            for sym in self._symbols
        ]

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        coin = instrument_id.rsplit(":", 1)[-1]
        code, step_sec = _INTERVAL_MAP.get(interval, ("1d", 86400))
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        raw = self._market.fetch_candles(coin, code, start_ms=start_ms, end_ms=end_ms)
        out: list[Bar] = []
        for row in raw:
            try:
                ts = datetime.fromtimestamp(int(row["t"]) / 1000, tz=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if not (start <= ts <= end):
                continue
            # available_at = the bar's CLOSE time (Hyperliquid gives it as "T"); fall back to ts + interval so
            # the PIT stamp is never earlier than when the bar could actually be observed.
            try:
                avail = datetime.fromtimestamp(int(row["T"]) / 1000, tz=timezone.utc)
            except (KeyError, TypeError, ValueError):
                from datetime import timedelta
                avail = ts + timedelta(seconds=step_sec)
            out.append(
                Bar(
                    instrument_id=instrument_id,
                    ts=ts,
                    interval=interval,
                    open=Decimal(str(row["o"])),
                    high=Decimal(str(row["h"])),
                    low=Decimal(str(row["l"])),
                    close=Decimal(str(row["c"])),
                    volume=Decimal(str(row["v"])),
                    available_at=avail,
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        return []
