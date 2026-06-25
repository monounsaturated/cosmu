# intent: the crypto DataAdapter — wraps the Binance OHLCV provider + point-in-time alt-data + universe calendar
# behind core.DataAdapter; inputs: a symbol set + injected providers; outputs: core Instruments/Bars/Features that
# are point-in-time honest (a bar is known only at its close, alt-data only by its availability time); invariants:
# no survivorship (universe is as-of), no look-ahead (available_at stamps), and the same contract serves every class.

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument
from cosmu.data.market import MarketDataProvider, default_crypto_reference
from cosmu.data.universe_calendar import Listing, UniverseCalendar

_VENUE = "binance"
_INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


class AltReader(Protocol):
    """Point-in-time alt-data reader — both AltDataStore (JSONL) and PgAltDataStore (Postgres) satisfy this."""

    def read_asof(self, provider: str, symbol: str, metric: str, as_of: datetime) -> list: ...


def instrument_id(symbol: str) -> str:
    return f"crypto:{_VENUE}:{symbol}"


def _symbol_of(instrument_id_: str) -> str:
    return instrument_id_.rsplit(":", 1)[-1]


class CryptoDataAdapter:
    """Binance spot, long-only. `alt_metrics` lists the (provider, metric) alt-data series to expose as features
    (e.g. ("binance","funding_rate"), ("alternative.me","fear_greed")); each is read point-in-time as of the query."""

    asset_class = AssetClass.CRYPTO

    def __init__(
        self,
        symbols: list[str],
        *,
        market_provider: MarketDataProvider | None = None,
        alt_reader: AltReader | None = None,
        alt_metrics: tuple[tuple[str, str], ...] = (),
        listings: list[Listing] | None = None,
        transform_versions: dict[str, str] | None = None,
    ) -> None:
        self._symbols = list(symbols)
        self._market = market_provider or default_crypto_reference()
        self._alt = alt_reader
        self._alt_metrics = alt_metrics
        self._calendar = UniverseCalendar(listings) if listings else None
        self._tv = transform_versions or {}

    def universe(self, as_of: datetime) -> list[Instrument]:
        symbols = self._calendar.eligible(as_of) if self._calendar else self._symbols
        out: list[Instrument] = []
        for sym in symbols:
            listing = self._listing_for(sym)
            out.append(
                Instrument(
                    id=instrument_id(sym), symbol=sym, asset_class=AssetClass.CRYPTO, venue=_VENUE,
                    tick_size=Decimal("0.00000001"), lot_size=Decimal("0.00000001"), min_notional=Decimal("10"),
                    quote_ccy="USDT", listed_at=listing.listed_at if listing else None,
                    delisted_at=listing.delisted_at if listing else None,
                )
            )
        return out

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        symbol = _symbol_of(instrument_id)
        step = timedelta(seconds=_INTERVAL_SECONDS.get(interval, 86400))
        # generous limit; we filter to [start, end] after fetch (provider returns most-recent `limit` bars)
        raw = self._market.fetch_bars(symbol, interval, limit=1000)
        out: list[Bar] = []
        for b in raw:
            if not (start <= b.ts <= end):
                continue
            out.append(
                Bar(
                    instrument_id=instrument_id, ts=b.ts, interval=interval,
                    open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume,
                    available_at=b.ts + step,  # a bar is only known once it has closed (point-in-time)
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        if self._alt is None:
            return []
        symbol = _symbol_of(instrument_id)
        out: list[Feature] = []
        for provider, metric in self._alt_metrics:
            # market-wide series (e.g. Fear & Greed) are stored under "MARKET"
            key = "MARKET" if metric == "fear_greed" else symbol
            for p in self._alt.read_asof(provider, key, metric, as_of):
                out.append(
                    Feature(
                        name=metric, instrument_id=instrument_id, ts=p.ts, available_at=p.available_at,
                        value=float(p.value), transform_version=self._tv.get(metric, "raw-v1"),
                    )
                )
        return out

    def _listing_for(self, symbol: str) -> Listing | None:
        if not self._calendar:
            return None
        return next((listing for listing in self._calendar._listings if listing.symbol == symbol), None)  # noqa: SLF001
