# intent: the asset-agnostic core — the typed contracts every asset class, engine, and adapter implements;
# inputs: none (pure types); outputs: Protocols + frozen records shared across crypto/equity/fx/prediction;
# invariants: one shape per concept, point-in-time stamps are mandatory, and the same code path serves all four classes.

from __future__ import annotations

from cosmu.core.calendars import TradingCalendar, calendar_for
from cosmu.core.interfaces import (
    AssetClass,
    Bar,
    DataAdapter,
    ExecutionAdapter,
    Feature,
    Fill,
    Instrument,
    Order,
    OrderId,
    Position,
    ProductType,
    Signal,
    SignalProducer,
    Strategy,
    Tick,
)

__all__ = [
    "AssetClass",
    "Bar",
    "DataAdapter",
    "ExecutionAdapter",
    "Feature",
    "Fill",
    "Instrument",
    "Order",
    "OrderId",
    "Position",
    "ProductType",
    "Signal",
    "SignalProducer",
    "Strategy",
    "Tick",
    "TradingCalendar",
    "calendar_for",
]
