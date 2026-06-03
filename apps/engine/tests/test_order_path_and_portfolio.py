# The single order path (master/execution.py) + sim portfolio (master/portfolio.py): the gauntlet rejects a
# missing-SL order and an averaging-down/martingale sizing, paper-fills when live is off, and never routes live
# without toggle+keys+gate. Plus portfolio P&L, drawdown, and the daily-loss auto-disarm.

from __future__ import annotations

from decimal import Decimal

from cosmu.adapters.exec.binance import BinanceSpotExecutionAdapter
from cosmu.config.settings import RiskSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.master.execution import IntendedOrder, execute_orders
from cosmu.master.portfolio import Portfolio
from cosmu.spine.venue import default_catalog

CATALOG = default_catalog()


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/exec.sqlite3"))


def _ok_intent(**kw) -> IntendedOrder:
    base = dict(
        strategy_version_id="sv1",
        symbol="BTCUSDT",
        venue_id="binance",
        side=1,
        qty=Decimal("0.05"),
        price=Decimal("65000"),
        stop_loss=Decimal("61000"),
        take_profit=Decimal("72000"),
        conviction=Decimal("0.6"),
        gate_passed=True,
    )
    base.update(kw)
    return IntendedOrder(**base)


def _run(store, intents, *, live_enabled=False, kill=False, adapter=None):
    pf = Portfolio(store, daily_loss_cap=Decimal("250"))
    adapter = adapter or BinanceSpotExecutionAdapter(client=None, mode="disabled")
    return pf, execute_orders(
        intents, live_enabled=live_enabled, kill_switch=kill, adapter=adapter,
        store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG,
    )


def test_gauntlet_rejects_missing_sl(tmp_path):
    store = _store(tmp_path)
    _, outcomes = _run(store, [_ok_intent(stop_loss=None)])
    assert outcomes[0].accepted is False
    assert "missing_sl_tp" in outcomes[0].issues
    assert store.row("SELECT id FROM events WHERE kind = 'order_rejected'") is not None


def test_paper_fills_when_live_off(tmp_path):
    store = _store(tmp_path)
    pf, outcomes = _run(store, [_ok_intent()], live_enabled=False)
    assert outcomes[0].accepted and outcomes[0].routed_live is False and outcomes[0].venue == "sim"
    pos = pf.position("btc-usdt-binance", "sim", strategy_version_id="sv1")
    assert pos is not None and pos.qty == Decimal("0.05")
    assert store.row("SELECT id FROM executions WHERE is_paper = 1") is not None


def test_no_live_route_without_keys_even_with_toggle_and_gate(tmp_path):
    store = _store(tmp_path)
    # toggle ON + gate passed, but adapter disabled (no keys) -> MUST paper-simulate, never route live.
    _, outcomes = _run(store, [_ok_intent(gate_passed=True)], live_enabled=True)
    assert outcomes[0].accepted and outcomes[0].routed_live is False and outcomes[0].venue == "sim"


def test_no_live_route_without_gate_pass(tmp_path):
    store = _store(tmp_path)

    class _Mock:
        def create_order(self, *a, **k):
            return {"id": "v1", "clientOrderId": k.get("params", {}).get("clientOrderId") or a[-1]["clientOrderId"]}

        def fetch_order(self, *a, **k):
            raise ValueError("nf")

    adapter = BinanceSpotExecutionAdapter(client=_Mock(), mode="testnet")
    _, outcomes = _run(store, [_ok_intent(gate_passed=False)], live_enabled=True, adapter=adapter)
    assert outcomes[0].routed_live is False  # gate not passed -> never live


def test_live_route_when_all_conditions_hold(tmp_path):
    store = _store(tmp_path)
    created = []

    class _Mock:
        def create_order(self, symbol, type, side, amount, price, params):  # noqa: A002
            created.append(params["clientOrderId"])
            return {"id": "v1", "clientOrderId": params["clientOrderId"], "symbol": symbol}

        def fetch_order(self, id, symbol=None, params=None):  # noqa: A002
            raise ValueError("nf")

    adapter = BinanceSpotExecutionAdapter(client=_Mock(), mode="testnet")
    _, outcomes = _run(store, [_ok_intent()], live_enabled=True, adapter=adapter)
    assert outcomes[0].routed_live is True and outcomes[0].venue == "testnet"
    assert len(created) == 1
    assert store.row("SELECT id FROM events WHERE kind = 'order_submitted_live'") is not None
    assert store.row("SELECT id FROM executions WHERE is_paper = 0") is not None


def test_kill_switch_blocks_live_route(tmp_path):
    store = _store(tmp_path)

    class _Mock:
        def create_order(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("kill switch must block live submit")

        def fetch_order(self, *a, **k):
            raise ValueError("nf")

    adapter = BinanceSpotExecutionAdapter(client=_Mock(), mode="testnet")
    _, outcomes = _run(store, [_ok_intent()], live_enabled=True, kill=True, adapter=adapter)
    assert outcomes[0].routed_live is False


def test_idempotent_no_double_fill(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    intent = _ok_intent(client_order_id="cosmu-fixed")
    for _ in range(2):
        execute_orders([intent], live_enabled=False, kill_switch=False, adapter=adapter, store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG)
    rows = store.rows("SELECT id FROM executions")
    assert len(rows) == 1  # replay did not double-fill
    pos = pf.position("btc-usdt-binance", "sim", strategy_version_id="sv1")
    assert pos.qty == Decimal("0.05")


def test_averaging_down_after_loss_is_rejected(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    adapter = BinanceSpotExecutionAdapter(client=None, mode="disabled")
    # open a long, then close at a loss to set last_was_loss, then try to add below avg -> martingale + avg-down
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=1, qty=Decimal("0.05"), price=Decimal("65000"), fee=Decimal("1"), strategy_version_id="sv1")
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=-1, qty=Decimal("0.02"), price=Decimal("60000"), fee=Decimal("1"), strategy_version_id="sv1")
    out = execute_orders(
        [_ok_intent(price=Decimal("58000"), stop_loss=Decimal("55000"), take_profit=Decimal("70000"))],
        live_enabled=False, kill_switch=False, adapter=adapter, store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG,
    )
    assert out[0].accepted is False
    assert "averaging_down" in out[0].issues or "martingale_after_loss" in out[0].issues


def test_portfolio_pnl_drawdown_and_daily_loss_auto_disarm(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store, bankroll=Decimal("100000"), daily_loss_cap=Decimal("250"))
    pf.apply_fill(instrument_id="btc-usdt-binance", symbol="BTCUSDT", venue="sim", side=1, qty=Decimal("1"), price=Decimal("65000"), fee=Decimal("0"), strategy_version_id="sv1")
    up = pf.mark_to_market({"btc-usdt-binance": Decimal("66000")})
    assert up["pnl"] > 0 and up["drawdown"] == 0
    down = pf.mark_to_market({"btc-usdt-binance": Decimal("64000")})
    assert down["pnl"] < 0 and down["drawdown"] > 0
    status = pf.daily_loss()
    assert status.daily_loss >= Decimal("1000") and status.tripped is True  # > 250 cap -> auto-disarm trips
