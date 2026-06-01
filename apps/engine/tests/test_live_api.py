# Live-trading API surface: /toggle/live requires confirm (and live stays OFF without it), /live/activate
# requires confirm + returns caps/eligible, /live/defund works, /live/positions has the right shape and reports
# mode "paper" with no keys. Secrets never appear in any response. No network, no lifespan: the module store +
# settings are pointed at a temp sqlite DB with no exchange keys (paper), following the existing API-test pattern.

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import LiveSettings, Settings
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/live_api.sqlite3",
        binance_api_key=None,
        binance_api_secret=None,
        binance_testnet_api_key=None,
        binance_testnet_api_secret=None,
        live=LiveSettings(),
    )
    store = Store(settings)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app)  # no `with` → lifespan backtest does not run


def test_toggle_requires_confirm_and_stays_off(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/toggle/live", json={"enabled": True, "confirm": False}).json()
    assert body["enabled"] is False and body["requires_confirm"] is True
    assert c.post("/toggle/live", json={"enabled": True, "confirm": True}).json()["enabled"] is True


def test_activate_requires_confirm(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/activate", json={"per_strategy_cap": 1000, "global_cap": 5000, "max_daily_loss": 200, "confirm": False}).json()
    assert body["armed"] is False and body["reason"]


def test_activate_arms_and_returns_caps_and_eligible(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/activate", json={"per_strategy_cap": 1000, "global_cap": 5000, "max_daily_loss": 200, "confirm": True}).json()
    assert body["armed"] is True
    assert body["caps"] == {"per_strategy_cap": 1000.0, "global_cap": 5000.0, "max_daily_loss": 200.0}
    assert isinstance(body["eligible"], list)


def test_live_positions_shape_and_paper_mode_without_keys(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.get("/live/positions").json()
    assert set(body) == {"armed", "mode", "daily_loss", "caps", "positions"}
    assert body["mode"] == "paper"  # no keys -> paper
    assert body["armed"] is False
    assert set(body["caps"]) == {"per_strategy_cap", "global_cap", "max_daily_loss"}
    assert isinstance(body["positions"], list)


def test_defund_all_ok(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/defund", json={"scope": "all"}).json()
    assert body["ok"] is True and isinstance(body["defunded"], list)


def test_no_secrets_in_responses(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for path in ("/live/positions", "/portfolio"):
        text = c.get(path).text.lower()
        assert "secret" not in text
