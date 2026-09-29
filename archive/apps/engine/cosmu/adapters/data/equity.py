# intent: the equity DataAdapter — free daily bars (Stooq) + FRED macro behind core.DataAdapter; inputs: a symbol
# set + injected providers; outputs: core Instruments/Bars/Features that are point-in-time honest (a daily bar is
# known only after its session, macro only by its FRED release time); invariants: same contract as every class,
# no look-ahead (available_at stamps), AND an explicit, declared survivorship limit — free bars list only
# currently-traded names, so this proves cross-asset signal PRESENCE, not deployable capacity (Norgate at live).

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from cosmu.adapters.data.crypto import AltReader
from cosmu.core.interfaces import AssetClass, Bar, Feature, Instrument
from cosmu.data.market import MarketDataProvider, StooqDailyBarsProvider
from cosmu.data.universe_calendar import Listing, UniverseCalendar

_VENUE = "stooq"


def instrument_id(symbol: str) -> str:
    return f"equity:{_VENUE}:{symbol}"


def _symbol_of(instrument_id_: str) -> str:
    return instrument_id_.rsplit(":", 1)[-1]


class EquityDataAdapter:
    """Free daily US equity bars (long-only). `macro_metrics` lists the (provider, FRED-series-id) macro
    series exposed as features (e.g. ("fred","T10Y2Y")); each is read point-in-time as of the query. Macro
    is market-wide, so it is stored/read under the "MARKET" key, not per symbol."""

    asset_class = AssetClass.EQUITY
    # Free bars (Stooq/Yahoo-free) have no delisted names → the universe is survivorship-biased. Declared,
    # not hidden: this gate tests whether the signal EXISTS cross-asset, not whether it is deployable at size.
    survivorship_complete = False

    def __init__(
        self,
        symbols: list[str],
        *,
        market_provider: MarketDataProvider | None = None,
        alt_reader: AltReader | None = None,
        macro_metrics: tuple[tuple[str, str], ...] = (),
        listings: list[Listing] | None = None,
        transform_versions: dict[str, str] | None = None,
    ) -> None:
        self._symbols = list(symbols)
        self._market = market_provider or StooqDailyBarsProvider()
        self._alt = alt_reader
        self._macro_metrics = macro_metrics
        self._calendar = UniverseCalendar(listings) if listings else None
        self._tv = transform_versions or {}

    def universe(self, as_of: datetime) -> list[Instrument]:
        symbols = self._calendar.eligible(as_of) if self._calendar else self._symbols
        out: list[Instrument] = []
        for sym in symbols:
            listing = self._listing_for(sym)
            out.append(
                Instrument(
                    id=instrument_id(sym), symbol=sym, asset_class=AssetClass.EQUITY, venue=_VENUE,
                    tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1"),
                    quote_ccy="USD", listed_at=listing.listed_at if listing else None,
                    delisted_at=listing.delisted_at if listing else None,
                )
            )
        return out

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]:
        symbol = _symbol_of(instrument_id)
        raw = self._market.fetch_bars(symbol, interval, limit=10000)
        out: list[Bar] = []
        for b in raw:
            if not (start <= b.ts <= end):
                continue
            out.append(
                Bar(
                    instrument_id=instrument_id, ts=b.ts, interval=interval,
                    open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume,
                    available_at=b.ts + timedelta(days=1),  # a daily bar is known only after its session closes
                )
            )
        return out

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        if self._alt is None:
            return []
        out: list[Feature] = []
        for provider, metric in self._macro_metrics:
            for p in self._alt.read_asof(provider, "MARKET", metric, as_of):  # macro is market-wide
                out.append(
                    Feature(
                        name=metric, instrument_id=instrument_id, ts=p.ts, available_at=p.available_at,
                        value=float(p.value), transform_version=self._tv.get(metric, "macro-regime-v1"),
                    )
                )
        return out

    def _listing_for(self, symbol: str) -> Listing | None:
        if not self._calendar:
            return None
        return next((listing for listing in self._calendar._listings if listing.symbol == symbol), None)  # noqa: SLF001
