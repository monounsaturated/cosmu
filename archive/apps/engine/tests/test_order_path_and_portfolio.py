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
    # explicit bankroll: these tests exercise order routing, not the $1k sim default
    pf = Portfolio(store, bankroll=Decimal("100000"), daily_loss_cap=Decimal("250"))
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


class _RecordingAdapter:
    """A live adapter that records (or rejects) submits — for the venue-shaping + submit-guard tests."""

    def __init__(self, venue="polymarket", mode="testnet", *, raises=False):
        from cosmu.core.interfaces import AssetClass

        self.venue = venue
        self.asset_class = AssetClass.PREDICTION if venue == "polymarket" else AssetClass.CRYPTO
        self.mode = mode
        self.orders: list = []
        self._raises = raises

    @property
    def active(self) -> bool:
        return True

    def submit(self, order):
        from cosmu.core.interfaces import OrderId

        if self._raises:
            raise RuntimeError("venue rejected the order")
        self.orders.append(order)
        return OrderId(venue=self.venue, client_order_id=order.client_order_id, venue_order_id="V1")

    def cancel(self, order_id):  # pragma: no cover
        pass

    def positions(self):
        return []

    def fills(self, since):
        return []


def test_prediction_order_is_coerced_to_limit_at_the_mark(tmp_path):
    """A prediction CLOB (Polymarket) has no market order. The executor's default order_type is 'market', so
    the order path MUST coerce a prediction order to a LIMIT at the mark (the share probability) before submit
    — else the adapter rejects it. Also: the symbol is NOT ccxt-mangled for a non-crypto venue."""
    store = _store(tmp_path)
    adapter = _RecordingAdapter(venue="polymarket", mode="testnet")
    intent = _ok_intent(
        strategy_version_id="pm1", symbol="PM-FED-CUT-2026", venue_id="polymarket",
        qty=Decimal("10"), price=Decimal("0.42"), stop_loss=Decimal("0.30"), take_profit=Decimal("0.60"),
    )
    _, outcomes = _run(store, [intent], live_enabled=True, adapter=adapter)
    assert outcomes[0].routed_live is True and outcomes[0].venue == "testnet"
    assert len(adapter.orders) == 1
    o = adapter.orders[0]
    assert o.order_type == "limit" and o.limit_price == Decimal("0.42")  # market → limit at the mark
    assert o.instrument_id == "PM-FED-CUT-2026"  # not ccxt-mangled (prediction venue)


def test_submit_failure_is_audited_and_skipped_never_crashes(tmp_path):
    """A venue/adapter error on submit MUST NOT crash the tick nor book a phantom fill — it is audited and the
    order is skipped (position unchanged, retried next tick)."""
    store = _store(tmp_path)
    adapter = _RecordingAdapter(venue="polymarket", mode="testnet", raises=True)
    intent = _ok_intent(
        strategy_version_id="pm2", symbol="PM-FED-CUT-2026", venue_id="polymarket",
        qty=Decimal("10"), price=Decimal("0.42"), stop_loss=Decimal("0.30"), take_profit=Decimal("0.60"),
    )
    pf, outcomes = _run(store, [intent], live_enabled=True, adapter=adapter)  # must NOT raise
    assert outcomes[0].accepted is False and "submit_failed" in outcomes[0].issues
    ev = store.row("SELECT payload FROM events WHERE kind = 'order_submit_failed'")
    assert ev is not None
    # SECURITY: the raw exception message is NOT persisted (it can carry key/secret material) — only the type.
    import json as _json
    payload = _json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
    assert payload.get("error_type") == "RuntimeError" and "error" not in payload
    assert store.row("SELECT id FROM executions WHERE strategy_version_id = 'pm2'") is None  # nothing booked
    assert pf.position("pm-fed-cut", "testnet", strategy_version_id="pm2") is None


def test_live_submit_not_repeated_after_a_prior_submit_event(tmp_path):
    """Cross-restart double-submit guard: once a live submit for a client_order_id is on the ledger, a re-run
    must NOT place a second REAL order (Polymarket CLOB has no native client-id dedup). Re-running the same
    intent calls the adapter exactly once."""
    store = _store(tmp_path)
    adapter = _RecordingAdapter(venue="polymarket", mode="testnet")
    intent = _ok_intent(
        strategy_version_id="pm3", symbol="PM-FED-CUT-2026", venue_id="polymarket",
        qty=Decimal("10"), price=Decimal("0.42"), stop_loss=Decimal("0.30"), take_profit=Decimal("0.60"),
    )
    _run(store, [intent], live_enabled=True, adapter=adapter)   # first run submits
    _run(store, [intent], live_enabled=True, adapter=adapter)   # re-run (e.g. after a restart) must NOT re-submit
    assert len(adapter.orders) == 1  # exactly one real order, never two


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
    pf = Portfolio(store, bankroll=Decimal("100000"))
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


def test_sim_fill_pays_slippage_adverse_both_ways(tmp_path):
    """A SIM fill crosses the half-spread the ADVERSE way at the same 5 bps base the gate-lane backtest
    charges: a buy fills ABOVE the mark, a sell BELOW — so paper P&L can never be flattered relative
    to the screen that funded the track. The recorded execution price is the slipped fill, not the mark."""
    store = _store(tmp_path)
    pf, _ = _run(store, [_ok_intent()], live_enabled=False)
    pos = pf.position("btc-usdt-binance", "sim", strategy_version_id="sv1")
    assert pos.avg_price == Decimal("65000") * Decimal("1.0005")  # buy fills 5 bps ABOVE the 65000 mark

    out = execute_orders(
        [_ok_intent(side=-1, qty=Decimal("0.05"), stop_loss=None, take_profit=None, reduce_only=True)],
        live_enabled=False, kill_switch=False, adapter=BinanceSpotExecutionAdapter(client=None, mode="disabled"),
        store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG,
    )
    assert out[0].accepted
    row = store.row("SELECT price FROM executions WHERE side = 'sell'")
    assert Decimal(str(row["price"])) == Decimal("65000") * Decimal("0.9995")  # sell fills 5 bps BELOW
    pos = pf.position("btc-usdt-binance", "sim", strategy_version_id="sv1")
    assert pos.qty == 0
    # Round trip at a flat mark loses exactly spread + fees — the honest cost floor, never a free flip.
    assert pos.realized_pnl < 0


def test_reduce_only_close_is_exempt_from_entry_checks_but_must_reduce(tmp_path):
    """A reduce-only exit needs no brackets and must clear even when entry-shaped limits would block it;
    but an order flagged reduce_only that does NOT genuinely reduce an existing position is rejected."""
    store = _store(tmp_path)
    pf, _ = _run(store, [_ok_intent()], live_enabled=False)

    # No position to reduce on ETH → rejected (reduce_only can never OPEN exposure).
    out = execute_orders(
        [_ok_intent(symbol="ETHUSDT", side=-1, qty=Decimal("1"), price=Decimal("3000"),
                    stop_loss=None, take_profit=None, reduce_only=True)],
        live_enabled=False, kill_switch=False, adapter=BinanceSpotExecutionAdapter(client=None, mode="disabled"),
        store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG,
    )
    assert out[0].accepted is False
    assert "reduce_only_not_reducing" in out[0].issues

    # A genuine close clears WITHOUT brackets (a normal sell without SL/TP would trip missing_sl_tp).
    out = execute_orders(
        [_ok_intent(side=-1, qty=Decimal("0.05"), stop_loss=None, take_profit=None, reduce_only=True)],
        live_enabled=False, kill_switch=False, adapter=BinanceSpotExecutionAdapter(client=None, mode="disabled"),
        store=store, portfolio=pf, risk=RiskSettings(), catalog=CATALOG,
    )
    assert out[0].accepted is True
    assert pf.position("btc-usdt-binance", "sim", strategy_version_id="sv1").qty == 0


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
