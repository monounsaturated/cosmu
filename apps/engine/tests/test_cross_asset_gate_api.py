# API test for POST /research/cross-asset-gate (synthetic fallback path). No network, no keys, no lifespan:
# point the module store at a temp sqlite DB and an empty alt store so the endpoint takes the synthetic
# branch, then assert the response matches the shared CrossAssetVerdict contract (snake_case).

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataStore
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None))
    monkeypatch.setattr(app_mod, "store", store)
    # empty alt store → no ingested cross-asset data → endpoint takes the synthetic fallback branch
    monkeypatch.setattr(app_mod, "_alt_store", lambda: AltDataStore(root=tmp_path / "alt_empty"))
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


_CONTRACT_KEYS = {
    "decision", "passed", "price_only_return", "single_alt_return", "xasset_return",
    "buy_and_hold_return", "xasset_dsr", "single_alt_dsr", "cscv_pbo", "regimes_positive",
    "num_trades", "max_drawdown", "attempts", "drop_one_source", "drop_one_class",
    "reasons", "bar", "data_source",
}


def test_cross_asset_gate_synthetic_returns_valid_verdict(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/research/cross-asset-gate", json={})
    assert resp.status_code == 200
    body = resp.json()

    # full shared contract present, snake_case
    assert set(body) == _CONTRACT_KEYS
    assert body["data_source"] == "synthetic"
    assert body["decision"] in ("PASS", "STOP-narrow")
    assert isinstance(body["passed"], bool)
    assert isinstance(body["num_trades"], int)
    assert isinstance(body["attempts"], int)

    # drop-one reports are lists of the right row shape
    for row in body["drop_one_source"]:
        assert set(row) == {"source", "sharpe_without", "delta"}
    for row in body["drop_one_class"]:
        assert set(row) == {"asset_class", "sharpe_without", "delta"}
    assert {c["asset_class"] for c in body["drop_one_class"]} == {"crypto", "equity"}
    assert isinstance(body["bar"], dict) and body["bar"]


def test_cross_asset_gate_persists_verdict_and_event(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/research/cross-asset-gate", json={})
    assert resp.status_code == 200
    # the run is recorded for UI monitoring (gate_verdicts) and audited as an event
    assert app_mod.store.row("SELECT id FROM gate_verdicts ORDER BY id DESC LIMIT 1") is not None
    ev = app_mod.store.row("SELECT kind FROM events WHERE kind = 'cross_asset_gate_run' LIMIT 1")
    assert ev is not None
