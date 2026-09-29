# The LIVE orders control-panel surface: GET /live/orders lists ONLY real-venue orders (executions.is_paper=0)
# — never the sim/paper lane — and POST /live/orders/{id}/cancel resolves the order's venue exec adapter and
# calls its cancel, guarded so it never touches a sim/paper order and never 500s on an adapter error. No
# network, no lifespan: the module store + settings point at a temp sqlite DB; the cancel path injects a MOCK
# adapter (no exchange call). Mirrors test_live_api.py's client/seed pattern.

from __future__ import annotations

import json

import cosmu.api.app as app_mod
from cosmu.config.settings import LiveSettings, Settings
from cosmu.knowledge.store import Store, utcnow


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/live_orders.sqlite3",
        live=LiveSettings(),
        _env_file=None,  # hermetic: ignore .env.local so the x-api-key gate stays a test no-op
    )
    store = Store(settings)
    # app_mod.store/settings fan out to every router module (incl. live) via _CompatModule.__setattr__.
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app), store


def _run_id(store: Store) -> str:
    """A standing run row to satisfy the executions.run_id FK (mirrors master/execution._run_id)."""
    return store.insert(
        "runs",
        {"strategy_version_id": None, "mode": "orchestrated", "venue_id": None, "seed": 0, "started_at": utcnow(), "status": "running"},
    )


def _exec(store: Store, run_id: str, *, coid: str, venue: str, symbol: str, side: str, qty: str, price: str, is_paper: int) -> None:
    """Insert one execution row shaped like master/execution._write_execution: the fill_log JSON carries the
    client_order_id (the cancel anchor); is_paper distinguishes the real-venue book (0) from the sim lane (1)."""
    store.insert(
        "executions",
        {
            "run_id": run_id, "strategy_version_id": None, "instrument_id": f"{venue}:{symbol}", "venue_id": venue,
            "side": side, "qty": qty, "price": price, "fee": "0.1", "slippage": "0",
            "order_type": "market", "is_paper": is_paper, "ts": utcnow(),
            "fill_log": json.dumps({"client_order_id": coid, "symbol": symbol, "side": side, "qty": qty, "price": price}),
        },
    )


class _MockAdapter:
    """A core.ExecutionAdapter stand-in: records the cancel call (no network). `fail=True` simulates a venue
    rejection so the endpoint's honest-error path is exercised without an exchange."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.canceled: list[str] = []

    def cancel(self, order_id) -> None:  # noqa: ANN001 — core.OrderId
        if self.fail:
            raise RuntimeError("boom from venue")
        self.canceled.append(order_id.client_order_id)


# ── GET /live/orders ──────────────────────────────────────────────────────────────────────────────


def test_orders_empty_state_when_nothing_live(tmp_path, monkeypatch):
    c, _store = _client(tmp_path, monkeypatch)
    body = c.get("/live/orders").json()
    assert set(body) == {"armed", "mode", "orders"}
    assert body["orders"] == []     # honest empty — nothing armed
    assert body["armed"] is False
    assert body["mode"] == "sim"    # no keys → sim


def test_orders_lists_live_excludes_sim_paper(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-live-1", venue="binance", symbol="BTCUSDT", side="buy", qty="0.5", price="20000", is_paper=0)
    _exec(store, rid, coid="cosmu-sim-1", venue="sim", symbol="ETHUSDT", side="sell", qty="3", price="3000", is_paper=1)

    body = c.get("/live/orders").json()
    ids = {o["order_id"] for o in body["orders"]}
    assert ids == {"cosmu-live-1"}  # the is_paper=1 sim order is structurally excluded
    o = body["orders"][0]
    assert o["venue"] == "binance" and o["symbol"] == "BTCUSDT" and o["side"] == "buy"
    assert o["qty"] == 0.5 and o["price"] == 20000.0
    assert o["status"] == "working"  # no cancel on the ledger yet


def test_orders_status_reflects_canceled_event(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-c1", venue="binance", symbol="BTCUSDT", side="buy", qty="1", price="100", is_paper=0)
    store.append_event(actor="human", kind="order_canceled_live", ref_type="execution", ref_id=None,
                       payload={"client_order_id": "cosmu-c1", "venue": "binance"})
    body = c.get("/live/orders").json()
    assert body["orders"][0]["status"] == "canceled"


# ── POST /live/orders/{id}/cancel ─────────────────────────────────────────────────────────────────


def test_cancel_unknown_order_is_404(tmp_path, monkeypatch):
    c, _store = _client(tmp_path, monkeypatch)
    res = c.post("/live/orders/nope/cancel")
    assert res.status_code == 404


def test_cancel_refuses_sim_paper_order(tmp_path, monkeypatch):
    # A sim/paper order (is_paper=1) never reached a venue → there is nothing to cancel. Must 404, NEVER cancel.
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-paper-1", venue="sim", symbol="ETHUSDT", side="buy", qty="1", price="3000", is_paper=1)
    assert c.post("/live/orders/cosmu-paper-1/cancel").status_code == 404


def test_cancel_calls_adapter_and_audits(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-x1", venue="binance", symbol="BTCUSDT", side="buy", qty="1", price="100", is_paper=0)
    mock = _MockAdapter()
    monkeypatch.setattr("cosmu.adapters.exec.registry.adapter_for", lambda v, s: mock)

    body = c.post("/live/orders/cosmu-x1/cancel").json()
    assert body == {"canceled": True, "order_id": "cosmu-x1", "venue": "binance", "reason": None}
    assert mock.canceled == ["cosmu-x1"]  # the venue adapter's cancel was actually called with the coid
    # Audited as order_canceled_live → the order now reads 'canceled' on the panel.
    assert store.row("SELECT id FROM events WHERE kind = 'order_canceled_live'") is not None
    assert c.get("/live/orders").json()["orders"][0]["status"] == "canceled"


def test_cancel_already_canceled_is_idempotent(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-i1", venue="binance", symbol="BTCUSDT", side="buy", qty="1", price="100", is_paper=0)
    store.append_event(actor="human", kind="order_canceled_live", ref_type="execution", ref_id=None,
                       payload={"client_order_id": "cosmu-i1", "venue": "binance"})
    mock = _MockAdapter()
    monkeypatch.setattr("cosmu.adapters.exec.registry.adapter_for", lambda v, s: mock)

    body = c.post("/live/orders/cosmu-i1/cancel").json()
    assert body["canceled"] is True and body["reason"] == "already canceled"
    assert mock.canceled == []  # NO second venue call


def test_cancel_data_only_venue_is_honest_not_implemented(tmp_path, monkeypatch):
    # A data-only venue (no exec adapter wired) must report 'not implemented', never a fabricated cancel.
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-hl1", venue="hyperliquid", symbol="BTC", side="buy", qty="1", price="100", is_paper=0)
    body = c.post("/live/orders/cosmu-hl1/cancel").json()
    assert body["canceled"] is False
    assert "no execution adapter" in body["reason"]
    assert store.row("SELECT id FROM events WHERE kind = 'order_canceled_live'") is None  # nothing audited


def test_cancel_adapter_error_is_honest_not_500(tmp_path, monkeypatch):
    c, store = _client(tmp_path, monkeypatch)
    rid = _run_id(store)
    _exec(store, rid, coid="cosmu-e1", venue="binance", symbol="BTCUSDT", side="buy", qty="1", price="100", is_paper=0)
    monkeypatch.setattr("cosmu.adapters.exec.registry.adapter_for", lambda v, s: _MockAdapter(fail=True))

    res = c.post("/live/orders/cosmu-e1/cancel")
    assert res.status_code == 200  # never 500 the control plane
    body = res.json()
    assert body["canceled"] is False and "venue rejected cancel" in body["reason"]
    # The error type is surfaced, but no secret-bearing message leaks.
    assert "boom from venue" not in res.text
    assert store.row("SELECT id FROM events WHERE kind = 'order_canceled_live'") is None  # not audited on failure
