# API tests for the read-only GET /settings/keys inventory (no API auth — this is an internal tool).
# No network, no real keys, no lifespan: point the module store at a temp sqlite DB and assert the
# endpoint reports configured-vs-not honestly and NEVER echoes a secret value.

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None, api_secret_key=secret)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


def test_health_ok(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "cosmu-engine"


def test_settings_keys_open_no_auth(tmp_path, monkeypatch):
    # No API auth: the keys inventory is reachable without any header.
    client = _client(tmp_path, monkeypatch)
    assert client.get("/settings/keys").status_code == 200


_KEY_ROW_FIELDS = {"key", "env_var", "configured", "unlocks", "requirement", "cost", "where"}


def test_settings_keys_shape_and_never_leaks_values(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    body = client.get("/settings/keys").json()
    rows = body["rows"]
    assert rows, "expected a non-empty key inventory"
    for row in rows:
        assert set(row) == _KEY_ROW_FIELDS
        assert isinstance(row["configured"], bool)
        assert row["requirement"] in ("required", "optional", "live-only")
        assert row["cost"] in ("free", "paid")
        # SECURITY: the actual secret value must never appear anywhere in the payload.
        assert "s3cret-key-very-long" not in str(row)
    by_env = {r["env_var"]: r for r in rows}
    assert by_env["API_SECRET_KEY"]["configured"] is True
    assert by_env["LUNARCRUSH_API_KEY"]["configured"] is False
