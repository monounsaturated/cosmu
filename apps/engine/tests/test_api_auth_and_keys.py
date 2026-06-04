# API tests for the shared-secret gate (API_SECRET_KEY) and the read-only GET /settings/keys inventory.
# No network, no real keys, no lifespan: point the module store at a temp sqlite DB, set/clear the secret on
# the module settings, and assert the middleware + endpoint behave honestly.

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch, *, secret: str | None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None, api_secret_key=secret)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


def test_health_is_open_even_with_secret_set(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "cosmu-engine"


def test_protected_route_401_without_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    resp = client.get("/settings/keys")
    assert resp.status_code == 401


def test_protected_route_ok_with_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    resp = client.get("/settings/keys", headers={"X-API-Key": "s3cret-key-very-long"})
    assert resp.status_code == 200


def test_protected_route_401_with_wrong_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    resp = client.get("/settings/keys", headers={"X-API-Key": "nope"})
    assert resp.status_code == 401


def test_auth_disabled_when_no_secret(tmp_path, monkeypatch):
    # No API_SECRET_KEY → the gate is a no-op so local dev/tests run keyless, exactly as before.
    client = _client(tmp_path, monkeypatch, secret=None)
    resp = client.get("/settings/keys")
    assert resp.status_code == 200


_KEY_ROW_FIELDS = {"key", "env_var", "configured", "unlocks", "requirement", "cost", "where"}


def test_settings_keys_shape_and_never_leaks_values(tmp_path, monkeypatch):
    # The secret IS configured here; the endpoint must report configured:true but NEVER echo the value.
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    resp = client.get("/settings/keys", headers={"X-API-Key": "s3cret-key-very-long"})
    assert resp.status_code == 200
    body = resp.json()
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
    # API_SECRET_KEY is set in this client → reported configured, value withheld.
    assert by_env["API_SECRET_KEY"]["configured"] is True
    # An unset key (no LunarCrush in the test settings) is honestly reported as not configured.
    assert by_env["LUNARCRUSH_API_KEY"]["configured"] is False
