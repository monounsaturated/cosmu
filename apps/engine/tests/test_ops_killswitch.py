# The MANUAL capital-guard kill-switch route (api/routers/ops.py): POST /ops/killswitch force-closes funded
# holdings via the SAME reduce-only path the automatic guard uses — GLOBAL (scope='all') or one combo
# (scope='combo' + version_id). This is the ONE route the front kill button POSTs and Claude Code curls. Asserts:
# confirm is required (two-click safety); a global kill flattens a healthy funded track and audits it; combo scope
# only touches the named cell; a no-op with nothing funded; the x-api-key auth gate covers it like every route.
# Offline: temp sqlite Store, live OFF (sim-close — byte-identical to the paper executor's exits), no network.

from __future__ import annotations

from decimal import Decimal

import cosmu.api.app as app_mod
import cosmu.api.routers.ops as ops_mod
from cosmu.api.models import KillswitchRequest
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.portfolio import Portfolio
from cosmu.spine.venue import default_catalog

_INSTRUMENT = default_catalog().instrument("BTCUSDT", "binance").id
_SYMBOL = "BTCUSDT"
_VENUE = "binance"


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: the "unarmed" path must not inherit the dev box's real venue keys (else a live
    # adapter could resolve and the sim-close assertion would flip).
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/ops.sqlite3", openrouter_api_key=None, _env_file=None))


def _wire(monkeypatch, store: Store) -> None:
    """Point the ops router's module-level store/settings at our temp store (mirrors the live-router test wiring)."""
    monkeypatch.setattr(ops_mod, "store", store)
    monkeypatch.setattr(ops_mod, "settings", store.settings)


def _fund_track(store: Store, *, version_id: str, qty: Decimal, starting_capital: Decimal) -> None:
    """A FUNDED, HELD track: a strategy + version + tracks row (the cell) + a real open long on the sim book +
    one marked-equity snapshot, so the guard resolves it as a holding to protect."""
    if store.row("SELECT id FROM strategies WHERE id = 'strat1'") is None:
        store.rows("INSERT INTO strategies (id, name, thesis, origin, created_at) VALUES (?, ?, ?, ?, ?)",
                   ("strat1", "kill-test", "kill test", "test", utcnow()))
    store.rows(
        "INSERT INTO strategy_versions "
        "(id, strategy_id, spec, generated_code, code_hash, params, origin, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, "strat1", "{}", "", version_id, "{}", "test", "paper", utcnow()),
    )
    store.insert("tracks", {"strategy_version_id": version_id, "symbol": _SYMBOL, "venue_id": _VENUE,
                            "starting_capital": str(starting_capital), "equity": str(starting_capital),
                            "return_pct": "0.00", "updated_at": utcnow()})
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pf.apply_fill(instrument_id=_INSTRUMENT, symbol=_SYMBOL, venue="sim", side=1,
                  qty=qty, price=Decimal("50000"), fee=Decimal("0"), strategy_version_id=version_id)
    store.insert("portfolio_snapshots", {
        "scope": "track", "ref_id": f"{version_id}:{_SYMBOL}:{_VENUE}", "ts": utcnow(),
        "equity": str(starting_capital * Decimal("1.1")),  # healthy +10% (auto-guard would NOT touch it)
        "cash": "0.00", "positions_value": str(starting_capital * Decimal("1.1")),
        "pnl": "0.00", "drawdown": "0.0000",
    })


def _qty(store: Store, vid: str) -> Decimal:
    pf = Portfolio(store, bankroll=Decimal("100000"))
    pos = pf.position(_INSTRUMENT, "sim", strategy_version_id=vid)
    return pos.qty if pos else Decimal("0")


# --- direct-call behaviour (the route function) -----------------------------------------------------------------

def test_killswitch_requires_confirm(tmp_path, monkeypatch):
    # confirm omitted → nothing is touched (two-click safety); the funded position stays open.
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _fund_track(store, version_id="v1", qty=Decimal("0.02"), starting_capital=Decimal("1000"))

    resp = ops_mod.ops_killswitch(KillswitchRequest(scope="all", confirm=False))

    assert resp.triggered is False and resp.closed == 0
    assert "confirm" in (resp.reason or "")
    assert _qty(store, "v1") == Decimal("0.02")  # untouched
    assert store.row("SELECT id FROM events WHERE kind = 'ops_killswitch'") is None


def test_killswitch_global_flattens_a_healthy_track(tmp_path, monkeypatch):
    # A confirmed GLOBAL kill flattens even a perfectly healthy funded track (the operator backstop) + audits it.
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _fund_track(store, version_id="v1", qty=Decimal("0.02"), starting_capital=Decimal("1000"))

    resp = ops_mod.ops_killswitch(KillswitchRequest(scope="all", confirm=True))

    assert resp.triggered is True and resp.evaluated == 1 and resp.closed == 1
    assert _qty(store, "v1") == Decimal("0")  # flat
    # summary event on the ledger
    ev = store.row("SELECT id FROM events WHERE kind = 'ops_killswitch'")
    assert ev is not None
    # a sim reduce-only SELL booked (live OFF → sim-close, is_paper=1)
    sell = store.row("SELECT is_paper FROM executions WHERE side = 'sell' AND strategy_version_id = 'v1'")
    assert sell is not None and int(sell["is_paper"]) == 1


def test_killswitch_combo_only_targets_that_cell(tmp_path, monkeypatch):
    # scope='combo' closes ONLY the named version; a sibling funded track is left alone.
    store = _store(tmp_path)
    _wire(monkeypatch, store)
    _fund_track(store, version_id="v-target", qty=Decimal("0.02"), starting_capital=Decimal("1000"))
    _fund_track(store, version_id="v-other", qty=Decimal("0.02"), starting_capital=Decimal("1000"))

    resp = ops_mod.ops_killswitch(KillswitchRequest(scope="combo", version_id="v-target", confirm=True))

    assert resp.triggered is True and resp.closed == 1 and resp.version_id == "v-target"
    assert _qty(store, "v-target") == Decimal("0")        # closed
    assert _qty(store, "v-other") == Decimal("0.02")      # sibling untouched


def test_killswitch_noop_with_nothing_funded(tmp_path, monkeypatch):
    # Confirmed but nothing funded in scope → triggered=true, closed=0 (a clean no-op, not an error).
    store = _store(tmp_path)
    _wire(monkeypatch, store)

    resp = ops_mod.ops_killswitch(KillswitchRequest(scope="all", confirm=True))

    assert resp.triggered is True and resp.evaluated == 0 and resp.closed == 0
    assert store.row("SELECT id FROM executions") is None


# --- the route is mounted + behind the same x-api-key auth gate as every route ----------------------------------

def _client(tmp_path, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/ops_api.sqlite3", openrouter_api_key=None,
                        api_secret_key=secret, _env_file=None)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)      # fans out to every router via the back-compat seam
    monkeypatch.setattr(app_mod, "settings", settings)
    return TestClient(app_mod.app)  # no `with` → no lifespan/startup backtest


def test_killswitch_route_mounted_and_callable(tmp_path, monkeypatch):
    # The route exists and answers (no funded track → triggered=true, closed=0). confirm in the JSON body.
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/ops/killswitch", json={"scope": "all", "confirm": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered"] is True and body["closed"] == 0


def test_killswitch_route_behind_api_key(tmp_path, monkeypatch):
    # API_SECRET_KEY set → the kill-switch route 401s without the header (like every control-plane route) and
    # unlocks with it. This is what stops anyone with the engine URL from POSTing /ops/killswitch.
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    assert client.post("/ops/killswitch", json={"scope": "all", "confirm": True}).status_code == 401
    ok = client.post("/ops/killswitch", json={"scope": "all", "confirm": True},
                     headers={"x-api-key": "s3cret-key-very-long"})
    assert ok.status_code == 200 and ok.json()["triggered"] is True
