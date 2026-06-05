# intent: OKX DataAdapter — wraps OKX REST API v5 behind core.DataAdapter (spot + perp); point-in-time
# honest (available_at = bar close + interval); offline-testable via injected market_provider.
# Execution is NOT wired here — venue live_enabled=False until live interlock + 5 gates pass.

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument, ProductType

_VENUE = "okx"
_BASE_URL = "https://www.okx.com"
# OKX bar param → (api_code, interval_seconds)
_INTERVAL_MAP: dict[str, tuple[str, int]] = {
    "1m":  ("1m",  60),
    "5m":  ("5m",  300),
    "15m": ("15m", 900),
    "1h":  ("1H",  3600),
    "4h":  ("4H",  14400),
    "1d":  ("1D",  86400),
}


class OKXMarketProvider(Protocol):
    """Injectable provider — production uses the OKX REST API; tests inject a canned fixture."""

    def fetch_candles(self, inst_id: str, bar: str, *, limit: int) -> list[list[str]]: ...


class _LiveOKXProvider:
    """Fetches candles from OKX REST API v5 using stdlib urllib — no third-party deps."""

    def fetch_candles(self, inst_id: str, bar: str, *, limit: int) -> list[list[str]]:
        url = f"{_BASE_URL}/api/v5/market/candles?instId={inst_id}&bar={bar}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
        # OKX response: {"data": [[ts_ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm], ...]}
        return payload.get("data", [])


def _inst_id_to_product_type(symbol: str) -> ProductType:
    return ProductType.PERP if symbol.endswith("-SWAP") else ProductType.SPOT


class OKXDataAdapter:
    """OKX spot + perp bars behind core.DataAdapter. Venue: okx (live_enabled=False).

    `symbols` uses OKX instId format: BTC-USDT for spot, BTC-USDT-SWAP for perpetual swaps.
    Each symbol's product_type is inferred from the suffix (-SWAP → PERP, else SPOT)."""

    asset_class = AssetClass.CRYPTO

    def __init__(
        self,
        symbols: list[str],
        *,
        market_provider: OKXMarketProvider | None = None,
    ) -> None:
        self._symbols = list(symbols)
        self._market = market_provider or _LiveOKXProvider()

    def universe(self, as_of: datetime) -> list[Instrument]:
        return [
            Instrument(
                id=f"crypto:{_VENUE}:{sym}",
                symbol=sym,
                asset_class=AssetClass.CRYPTO,
                venue=_VENUE,
                tick_size=Decimal("0.1") if "BTC" in sym else Decimal("0.01"),
                lot_size=Decimal("0.001") if sym.endswith("-SWAP") else Decimal("0.00001"),
                min_notional=Decimal("1"),
                quote_ccy="USDT",
                product_type=_inst_id_to_product_type(sym),
            )
            for sym in self._symbols
        ]

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        sym = instrument_id.rsplit(":", 1)[-1]
        bar_code, step_sec = _INTERVAL_MAP.get(interval, ("1D", 86400))
        step = timedelta(seconds=step_sec)
        raw = self._market.fetch_candles(sym, bar_code, limit=300)
        out: list[Bar] = []
        for row in raw:
            ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
            if not (start <= ts <= end):
                continue
            out.append(
                Bar(
                    instrument_id=instrument_id,
                    ts=ts,
                    interval=interval,
                    open=Decimal(row[1]),
                    high=Decimal(row[2]),
                    low=Decimal(row[3]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[5]),
                    available_at=ts + step,
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        return []
