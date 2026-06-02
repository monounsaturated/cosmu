# intent: describe tradable instruments at actual venues; inputs: static/env catalog; outputs: VenueCatalog; invariants: fees, constraints, and venue names are explicit and mode-free.

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Venue(BaseModel):
    id: str
    name: str
    kind: Literal["crypto", "equity", "prediction"]
    adapter: str
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    min_notional: Decimal
    lot_size: Decimal
    enabled: bool = True


class Instrument(BaseModel):
    id: str
    venue_id: str
    symbol: str
    asset_class: Literal["crypto", "equity", "prediction"]
    tick_size: Decimal = Decimal("0.01")
    lot_size: Decimal = Decimal("0.0001")
    min_notional: Decimal = Decimal("10")
    active: bool = True


class VenueCatalog(BaseModel):
    venues: list[Venue] = Field(default_factory=list)
    instruments: list[Instrument] = Field(default_factory=list)

    def venue(self, venue_id: str) -> Venue:
        for venue in self.venues:
            if venue.id == venue_id:
                return venue
        raise KeyError(f"unknown venue: {venue_id}")

    def instrument(self, symbol: str, venue_id: str = "binance") -> Instrument:
        for instrument in self.instruments:
            if instrument.symbol == symbol and instrument.venue_id == venue_id:
                return instrument
        raise KeyError(f"unknown instrument: {symbol}@{venue_id}")


def default_catalog() -> VenueCatalog:
    return VenueCatalog(
        venues=[
            Venue(id="binance", name="Binance", kind="crypto", adapter="nautilus.binance", maker_fee_bps=Decimal("10"), taker_fee_bps=Decimal("10"), min_notional=Decimal("10"), lot_size=Decimal("0.0001")),
            Venue(id="ibkr", name="IBKR", kind="equity", adapter="nautilus.ibkr", maker_fee_bps=Decimal("0.5"), taker_fee_bps=Decimal("0.5"), min_notional=Decimal("1"), lot_size=Decimal("1")),
            Venue(id="polymarket", name="Polymarket", kind="prediction", adapter="nautilus.polymarket", maker_fee_bps=Decimal("0"), taker_fee_bps=Decimal("0"), min_notional=Decimal("1"), lot_size=Decimal("1")),
        ],
        instruments=[
            Instrument(id="btc-usdt-binance", venue_id="binance", symbol="BTCUSDT", asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.00001"), min_notional=Decimal("10")),
            Instrument(id="eth-usdt-binance", venue_id="binance", symbol="ETHUSDT", asset_class="crypto", tick_size=Decimal("0.01"), lot_size=Decimal("0.0001"), min_notional=Decimal("10")),
            Instrument(id="spy-ibkr", venue_id="ibkr", symbol="SPY", asset_class="equity", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
            Instrument(id="pm-fed-cut", venue_id="polymarket", symbol="PM-FED-CUT-2026", asset_class="prediction", tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1")),
        ],
    )

