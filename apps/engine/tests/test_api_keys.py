# API tests for the read-only GET /settings/keys inventory AND the shared-secret auth gate (the
# docs/KEYS.md contract: API_SECRET_KEY set → every route except /health requires a matching x-api-key;
# unset → open, local-dev only). No network, no real keys, no lifespan: point the module store at a temp
# sqlite DB and assert the endpoint reports configured-vs-not honestly and NEVER echoes a secret value.

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    # _env_file=None makes this hermetic: ignore the repo-root .env.local so the inventory reflects
    # ONLY explicit/test env (else a dev box with real keys false-fails the "unconfigured" assertions).
    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None, api_secret_key=secret, _env_file=None)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


def test_health_ok(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "cosmu-engine"


def test_settings_keys_open_when_no_secret_configured(tmp_path, monkeypatch):
    # No API_SECRET_KEY (local dev) → the gate is a no-op, exactly as docs/KEYS.md documents.
    client = _client(tmp_path, monkeypatch)
    assert client.get("/settings/keys").status_code == 200


def test_secret_set_requires_matching_header_on_every_route_but_health(tmp_path, monkeypatch):
    # API_SECRET_KEY set (production) → no header / wrong header = 401 on control-plane routes; the
    # platform healthcheck stays open; the right header unlocks. This is what stops anyone with the
    # engine URL from POSTing /toggle/live or /live/launch.
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    assert client.get("/settings/keys").status_code == 401
    assert client.get("/settings/keys", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.post("/toggle/live").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/settings/keys", headers={"x-api-key": "s3cret-key-very-long"}).status_code == 200


_KEY_ROW_FIELDS = {"key", "env_var", "configured", "unlocks", "requirement", "cost", "where"}


def test_settings_keys_shape_and_never_leaks_values(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    body = client.get("/settings/keys", headers={"x-api-key": "s3cret-key-very-long"}).json()
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
