# Cross-asset compatibility suite (Deliverable 4), first pass: contract conformance + calendars + a golden
# strategy + PIT, all parametrized over the four asset classes. PIT/leakage/parity deepen as real adapters land.

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.core import (
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
    Signal,
    Strategy,
    calendar_for,
)

ALL_CLASSES = list(AssetClass)


# --- tiny in-memory adapters that satisfy the Protocols, one per class -----------------------------

class FakeData:
    def __init__(self, asset_class: AssetClass) -> None:
        self.asset_class = asset_class
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        self._inst = Instrument(
            id=f"{asset_class}:X", symbol="X", asset_class=asset_class, venue="test",
            tick_size=Decimal("0.01"), lot_size=Decimal("1"), min_notional=Decimal("1"),
            quote_ccy="USD", listed_at=t0, delisted_at=None,
        )
        self._bars = [
            Bar(instrument_id=self._inst.id, ts=t0 + timedelta(days=i), interval="1d",
                open=Decimal("100"), high=Decimal("101"), low=Decimal("99"), close=Decimal("100"),
                volume=Decimal("10"), available_at=t0 + timedelta(days=i))
            for i in range(5)
        ]
        # one feature per day, available the same day (point-in-time honest)
        self._features = [
            Feature(name="signal_z", instrument_id=self._inst.id, ts=b.ts, available_at=b.available_at,
                    value=float(i - 2), transform_version="v1")
            for i, b in enumerate(self._bars)
        ]

    def universe(self, as_of: datetime) -> list[Instrument]:
        listed = self._inst.listed_at is None or as_of >= self._inst.listed_at
        delisted = self._inst.delisted_at is not None and as_of >= self._inst.delisted_at
        return [self._inst] if (listed and not delisted) else []

    def bars(self, instrument_id, start, end, interval):
        return [b for b in self._bars if start <= b.ts <= end and b.interval == interval]

    def features(self, instrument_id, as_of):
        return [f for f in self._features if f.available_at <= as_of]


class FakeExec:
    def __init__(self, asset_class: AssetClass) -> None:
        self.asset_class = asset_class
        self.venue = "test"
        self._submitted: dict[str, OrderId] = {}

    def submit(self, order: Order) -> OrderId:
        # idempotent: re-submitting the same client_order_id returns the same OrderId
        if order.client_order_id not in self._submitted:
            self._submitted[order.client_order_id] = OrderId(venue=self.venue, client_order_id=order.client_order_id)
        return self._submitted[order.client_order_id]

    def cancel(self, order_id: OrderId) -> None:
        self._submitted.pop(order_id.client_order_id, None)

    def positions(self) -> list[Position]:
        return []

    def fills(self, since: datetime) -> list[Fill]:
        return []


class GoldenStrategy:
    """One strategy, identical across every class: go long when the z-feature is positive."""

    strategy_id = "golden"

    def on_bar(self, bar: Bar, features: list[Feature]) -> list[Signal]:
        # current value = the most recent point-in-time feature for this name
        current = max((f for f in features if f.name == "signal_z"), key=lambda f: f.ts, default=None)
        z = current.value if current else 0.0
        direction = 1 if z > 0 else 0
        return [Signal(strategy_id=self.strategy_id, instrument_id=bar.instrument_id, ts=bar.ts,
                       direction=direction, strength=abs(z), horizon="1d")]


# --- 1. contract conformance ----------------------------------------------------------------------

@pytest.mark.parametrize("ac", ALL_CLASSES)
def test_data_adapter_conforms(ac):
    assert isinstance(FakeData(ac), DataAdapter)


@pytest.mark.parametrize("ac", ALL_CLASSES)
def test_execution_adapter_conforms(ac):
    assert isinstance(FakeExec(ac), ExecutionAdapter)


def test_golden_strategy_conforms():
    assert isinstance(GoldenStrategy(), Strategy)


# --- 2. golden strategy runs unchanged on all four classes -----------------------------------------

@pytest.mark.parametrize("ac", ALL_CLASSES)
def test_golden_strategy_runs_every_class(ac):
    data = FakeData(ac)
    strat = GoldenStrategy()
    end = datetime(2024, 1, 10, tzinfo=UTC)
    signals = []
    for bar in data.bars(f"{ac}:X", datetime(2024, 1, 1, tzinfo=UTC), end, "1d"):
        signals += strat.on_bar(bar, data.features(bar.instrument_id, bar.available_at))
    assert len(signals) == 5
    assert all(s.direction in (-1, 0, 1) for s in signals)
    assert signals[-1].direction == 1  # last z = +2


# --- 3. point-in-time: features never leak the future ---------------------------------------------

@pytest.mark.parametrize("ac", ALL_CLASSES)
def test_features_are_point_in_time(ac):
    data = FakeData(ac)
    as_of = datetime(2024, 1, 3, tzinfo=UTC)
    assert all(f.available_at <= as_of for f in data.features(f"{ac}:X", as_of))
    # nothing from the future is visible
    assert len(data.features(f"{ac}:X", as_of)) == 3


# --- 4. idempotent execution ----------------------------------------------------------------------

@pytest.mark.parametrize("ac", ALL_CLASSES)
def test_submit_is_idempotent(ac):
    ex = FakeExec(ac)
    order = Order(instrument_id=f"{ac}:X", side=1, qty=Decimal("1"), order_type="market",
                  limit_price=None, client_order_id="abc", ts=datetime(2024, 1, 1, tzinfo=UTC))
    assert ex.submit(order) == ex.submit(order)  # same id, no double order


# --- 5. per-class trading calendars ----------------------------------------------------------------

def test_crypto_and_prediction_trade_every_day():
    for ac in (AssetClass.CRYPTO, AssetClass.PREDICTION):
        cal = calendar_for(ac)
        assert cal.is_session(date(2024, 1, 6))  # a Saturday
        assert len(cal.sessions(date(2024, 1, 1), date(2024, 1, 7))) == 7


def test_fx_skips_weekends():
    cal = calendar_for(AssetClass.FX)
    assert cal.is_session(date(2024, 1, 5))       # Friday
    assert not cal.is_session(date(2024, 1, 6))   # Saturday
    assert len(cal.sessions(date(2024, 1, 1), date(2024, 1, 7))) == 5


def test_equity_skips_weekends_and_holidays():
    cal = calendar_for(AssetClass.EQUITY, holidays={date(2024, 1, 1)})  # New Year (a Monday)
    assert not cal.is_session(date(2024, 1, 1))   # holiday
    assert cal.is_session(date(2024, 1, 2))       # Tuesday
    assert len(cal.sessions(date(2024, 1, 1), date(2024, 1, 7))) == 4  # Tue-Fri, minus Mon holiday


def test_session_of_folds_weekend_back_to_prior_session():
    cal = calendar_for(AssetClass.FX)
    sat = datetime(2024, 1, 6, 3, 0, tzinfo=UTC)
    assert cal.session_of(sat) == date(2024, 1, 5)  # folds into Friday
