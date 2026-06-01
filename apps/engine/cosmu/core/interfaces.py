# intent: the asset-agnostic domain contracts (Deliverable 3) every class/engine/adapter implements;
# inputs: typed engine records; outputs: Protocols + frozen dataclasses; invariants: every market datum carries a
# point-in-time availability stamp, ids/quantities are exact (Decimal), and one shape serves crypto/equity/fx/prediction.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AssetClass(StrEnum):
    CRYPTO = "crypto"
    EQUITY = "equity"
    FX = "fx"
    PREDICTION = "prediction"


@dataclass(frozen=True)
class Instrument:
    """A tradable instrument. `delisted_at` doubles as expiry for prediction markets — both make the
    instrument absent from `universe(as_of)` afterwards (survivorship/expiry safety)."""

    id: str
    symbol: str
    asset_class: AssetClass
    venue: str
    tick_size: Decimal
    lot_size: Decimal
    min_notional: Decimal
    quote_ccy: str
    listed_at: datetime | None = None
    delisted_at: datetime | None = None


@dataclass(frozen=True)
class Bar:
    """An OHLCV bar at `interval`. `available_at` is when we'd actually have known it (point-in-time),
    not the bar close — the #1 guard against alt-data/look-ahead lies."""

    instrument_id: str
    ts: datetime
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    available_at: datetime


@dataclass(frozen=True)
class Tick:
    """A single trade/quote print — the Bar shape at trade granularity."""

    instrument_id: str
    ts: datetime
    price: Decimal
    size: Decimal
    available_at: datetime


@dataclass(frozen=True)
class Feature:
    """A normalized, point-in-time feature value. `transform_version` pins the frozen+tested transform (and,
    for FM/AutoML/RL producers, the model weights) so a survivor is re-runnable byte-for-byte."""

    name: str
    instrument_id: str
    ts: datetime
    available_at: datetime
    value: float
    transform_version: str


@dataclass(frozen=True)
class Signal:
    """A strategy's asset-agnostic intent. Prediction-market 'down' is expressed as buying the opposite side,
    so `direction` stays in {-1, 0, +1} for every class."""

    strategy_id: str
    instrument_id: str
    ts: datetime
    direction: int
    strength: float
    horizon: str


@dataclass(frozen=True)
class Position:
    instrument_id: str
    qty: Decimal
    avg_price: Decimal
    ts: datetime


@dataclass(frozen=True)
class OrderId:
    venue: str
    client_order_id: str
    venue_order_id: str | None = None


@dataclass(frozen=True)
class Order:
    """An order intent. `client_order_id` is the idempotency key — re-submitting the same id is a no-op
    at the venue, so a retried/replayed order never double-fills."""

    instrument_id: str
    side: int  # +1 buy, -1 sell
    qty: Decimal
    order_type: str  # "market" | "limit" | "maker" (post-only)
    limit_price: Decimal | None
    client_order_id: str
    ts: datetime


@dataclass(frozen=True)
class Fill:
    order_id: OrderId
    instrument_id: str
    side: int
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_ccy: str
    is_maker: bool
    ts: datetime


@runtime_checkable
class DataAdapter(Protocol):
    """One per asset class (crypto/equity/fx/prediction). All reads are point-in-time and survivorship-aware."""

    asset_class: AssetClass

    def universe(self, as_of: datetime) -> list[Instrument]:
        """Instruments tradable *as of* `as_of` — never the current set projected backwards."""

    def bars(self, instrument_id: str, start: datetime, end: datetime, interval: str) -> list[Bar]: ...

    def features(self, instrument_id: str, as_of: datetime) -> list[Feature]:
        """Point-in-time features known by `as_of` (latest revision available then)."""


@runtime_checkable
class ExecutionAdapter(Protocol):
    """One per venue, sitting behind NautilusTrader. `submit` is idempotent via the order's client_order_id."""

    venue: str
    asset_class: AssetClass

    def submit(self, order: Order) -> OrderId: ...
    def cancel(self, order_id: OrderId) -> None: ...
    def positions(self) -> list[Position]: ...
    def fills(self, since: datetime) -> list[Fill]:
        """Fills since `since`, for reconciliation against intended orders."""


@runtime_checkable
class Strategy(Protocol):
    """Identical across all four classes: reads a bar + its point-in-time features, emits intents."""

    def on_bar(self, bar: Bar, features: list[Feature]) -> list[Signal]: ...


@runtime_checkable
class SignalProducer(Protocol):
    """A Qlib factor / foundation-model / AutoML producer. Runs once; output is frozen as a PIT Feature
    snapshot (weights pinned in `version`) so backtests re-read it bit-identically instead of re-inferring."""

    name: str
    version: str

    def produce(self, instrument_id: str, as_of: datetime) -> list[Feature]: ...
