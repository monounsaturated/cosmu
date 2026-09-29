# OCO bracket placement after a live BUY fill + fill reconciliation (actual vs intended).

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
from cosmu.config.settings import RiskSettings, Settings
from cosmu.core.interfaces import Fill, OrderId
from cosmu.master.execution import (
    IntendedOrder,
    execute_orders,
    reconcile_fills,
)
from cosmu.master.portfolio import Portfolio
from cosmu.spine.venue import default_catalog


class MockCcxtWithOCO:
    """Mock ccxt client that records OCO bracket placement calls."""

    def __init__(self, *, oco_fails: bool = False) -> None:
        self.created: list[dict] = []
        self.oco_calls: list[dict] = []
        self._oco_fails = oco_fails
        self._orders_by_coid: dict[str, dict] = {}

    def create_order(self, symbol, type, side, amount, price, params):  # noqa: A002
        if type == "oco":
            if self._oco_fails:
                raise RuntimeError("OCO placement failed")
            call = {"symbol": symbol, "side": side, "amount": amount, "price": price, "params": params}
            self.oco_calls.append(call)
            return {"orderId": "oco-1", "listClientOrderId": params.get("listClientOrderId")}
        coid = params.get("clientOrderId", "unknown")
        raw = {"id": f"venue-{len(self.created)+1}", "clientOrderId": coid, "symbol": symbol, "side": side, "amount": amount}
        self.created.append(raw)
        self._orders_by_coid[coid] = raw
        return raw

    def fetch_order(self, id, symbol=None, params=None):  # noqa: A002
        coid = (params or {}).get("clientOrderId", id)
        if coid in self._orders_by_coid:
            return self._orders_by_coid[coid]
        raise ValueError("order not found")

    def cancel_order(self, id, symbol=None, params=None):  # noqa: A002
        return {"id": id}

    def fetch_balance(self, params=None):
        return {"total": {"BTC": "0.5", "USDT": "10000"}}

    def fetch_my_trades(self, symbol=None, since=None, limit=None, params=None):
        coid = list(self._orders_by_coid.keys())[-1] if self._orders_by_coid else "unknown"
        return [
            {
                "order": coid,
                "symbol": "BTC/USDT",
                "side": "buy",
                "amount": "0.05",
                "price": "65050",
                "fee": {"cost": "0.04", "currency": "USDT"},
                "takerOrMaker": "taker",
                "timestamp": 1_700_000_000_000,
            }
        ]


def _store(tmp_path) -> Store:
    from cosmu.knowledge.store import Store

    return Store(Settings(database_url=f"sqlite:///{tmp_path}/oco.sqlite3"))


def _intent(coid: str = "cosmu-test-oco") -> IntendedOrder:
    return IntendedOrder(
        strategy_version_id="sv-1",
        symbol="BTCUSDT",
        venue_id="binance",
        side=1,
        qty=Decimal("0.05"),
        price=Decimal("65000"),
        stop_loss=Decimal("61000"),
        take_profit=Decimal("72000"),
        conviction=Decimal("0.6"),
        gate_passed=True,
        order_type="market",
        client_order_id=coid,
    )


def test_oco_placed_after_live_buy(tmp_path):
    """After a live BUY fill, an OCO bracket is placed with TP and SL prices."""
    store = _store(tmp_path)
    mock = MockCcxtWithOCO()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")
    pf = Portfolio(store)
    catalog = default_catalog()

    outcomes = execute_orders(
        [_intent()],
        live_enabled=True,
        kill_switch=False,
        adapter=adapter,
        store=store,
        portfolio=pf,
        risk=RiskSettings(),
        catalog=catalog,
    )
    assert len(outcomes) == 1
    assert outcomes[0].routed_live
    assert len(mock.oco_calls) == 1
    oco = mock.oco_calls[0]
    assert oco["side"] == "sell"
    assert oco["price"] == 72000.0  # take profit
    assert oco["params"]["stopPrice"] == 61000.0  # stop loss
    assert oco["params"]["listClientOrderId"] == "cosmu-test-oco-oco"

    events = store.rows("SELECT * FROM events WHERE kind = 'oco_bracket_placed'")
    assert len(events) == 1


def test_oco_failure_logged_not_fatal(tmp_path):
    """If OCO placement fails, the parent buy still succeeds — failure is just logged."""
    store = _store(tmp_path)
    mock = MockCcxtWithOCO(oco_fails=True)
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")
    pf = Portfolio(store)
    catalog = default_catalog()

    outcomes = execute_orders(
        [_intent()],
        live_enabled=True,
        kill_switch=False,
        adapter=adapter,
        store=store,
        portfolio=pf,
        risk=RiskSettings(),
        catalog=catalog,
    )
    assert len(outcomes) == 1
    assert outcomes[0].accepted
    assert outcomes[0].routed_live
    assert len(mock.oco_calls) == 0  # OCO failed, not recorded

    events = store.rows("SELECT * FROM events WHERE kind = 'oco_bracket_failed'")
    assert len(events) == 1


def test_oco_not_placed_for_sell(tmp_path):
    """OCO brackets are only for BUY orders — sell orders skip OCO."""
    store = _store(tmp_path)
    mock = MockCcxtWithOCO()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")
    pf = Portfolio(store)
    catalog = default_catalog()

    sell_intent = IntendedOrder(
        strategy_version_id="sv-1",
        symbol="BTCUSDT",
        venue_id="binance",
        side=-1,
        qty=Decimal("0.05"),
        price=Decimal("65000"),
        stop_loss=Decimal("61000"),
        take_profit=Decimal("72000"),
        conviction=Decimal("0.6"),
        gate_passed=True,
        order_type="market",
        client_order_id="cosmu-test-sell",
    )

    execute_orders(
        [sell_intent],
        live_enabled=True,
        kill_switch=False,
        adapter=adapter,
        store=store,
        portfolio=pf,
        risk=RiskSettings(),
        catalog=catalog,
    )
    assert len(mock.oco_calls) == 0


def test_oco_not_placed_for_paper(tmp_path):
    """Paper orders skip OCO — no adapter interaction."""
    store = _store(tmp_path)
    mock = MockCcxtWithOCO()
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    pf = Portfolio(store)
    catalog = default_catalog()

    outcomes = execute_orders(
        [_intent()],
        live_enabled=False,
        kill_switch=False,
        adapter=adapter,
        store=store,
        portfolio=pf,
        risk=RiskSettings(),
        catalog=catalog,
    )
    assert all(not o.routed_live for o in outcomes)
    assert len(mock.oco_calls) == 0


def test_reconcile_fills_logs_slippage(tmp_path):
    """Reconciliation fetches actual fills, compares with intended, updates execution, logs slippage."""
    store = _store(tmp_path)
    mock = MockCcxtWithOCO()
    adapter = BinanceSpotExecutionAdapter(client=mock, mode="live")
    pf = Portfolio(store)
    catalog = default_catalog()

    # First: execute a live order (books fill at intended price 65000)
    coid = "cosmu-recon-1"
    mock._orders_by_coid.clear()
    execute_orders(
        [_intent(coid)],
        live_enabled=True,
        kill_switch=False,
        adapter=adapter,
        store=store,
        portfolio=pf,
        risk=RiskSettings(),
        catalog=catalog,
    )

    # Mock returns actual fill at 65050 (50 USDT slippage)
    mock_fills = mock.fetch_my_trades
    original_trades = mock_fills()
    original_trades[0]["order"] = "venue-1"

    # Run reconciliation
    events = reconcile_fills(adapter, store, pf, since=datetime(2024, 1, 1, tzinfo=UTC))
    assert len(events) >= 1

    recon = events[0]
    assert recon["intended_price"] == "65000"
    assert recon["actual_price"] == "65050"
    assert Decimal(recon["slippage"]) == Decimal("50")

    # Verify execution row was updated
    exec_row = store.row("SELECT price FROM executions LIMIT 1")
    assert exec_row is not None
    assert Decimal(str(exec_row["price"])) == Decimal("65050")

    # Verify event was logged
    recon_events = store.rows("SELECT * FROM events WHERE kind = 'fill_reconciled'")
    assert len(recon_events) >= 1


def test_reconcile_fills_disabled_adapter(tmp_path):
    """Reconciliation with a disabled adapter returns empty — no network calls."""
    store = _store(tmp_path)
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    pf = Portfolio(store)
    assert reconcile_fills(adapter, store, pf) == []
