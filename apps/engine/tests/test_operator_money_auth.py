# Engine-side proof of the two-tier money-path auth, DARK-LAUNCHED behind operator_auth_enforced.
#
# The load-bearing property is DARK-LAUNCH BYTE-IDENTITY: with operator_auth_enforced=False (the default),
# every existing auth path behaves EXACTLY as before — the two-tier check is a no-op and the boot-assert never
# fires. Then, only when the operator flips the flag ON *and* sets the secret, a money route requires a valid
# x-operator header, boot refuses when the secret is missing, and reduce-only/read routes stay unaffected.
#
# Hermetic: temp sqlite, no network, no lifespan/startup backtest (no `with` on the client), _env_file=None so
# the repo .env.local can't leak real keys into the assertions.

from __future__ import annotations

from types import SimpleNamespace

import pytest

import cosmu.api.app as app_mod
from cosmu.api._lifespan import _guard_production_auth
from cosmu.api._money_routes import is_money_mutation, normalize_path
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _client(tmp_path, monkeypatch, *, secret=None, operator_secret=None, operator_enforced=False):
    from fastapi.testclient import TestClient

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/api.sqlite3",
        openrouter_api_key=None,
        api_secret_key=secret,
        operator_secret_key=operator_secret,
        operator_auth_enforced=operator_enforced,
        _env_file=None,
    )
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


# ── DARK-LAUNCH BYTE-IDENTITY ─────────────────────────────────────────────────────────────────────────────
# operator_auth_enforced defaults False. The whole second tier must be inert: the ONLY auth is x-api-key, so a
# money route with a valid x-api-key succeeds WITHOUT any x-operator header — identical to before this change.


def test_default_flag_is_off():
    s = Settings(_env_file=None)
    assert s.operator_auth_enforced is False
    assert s.operator_secret_key is None


def test_dark_launch_money_route_unaffected_without_operator_header(tmp_path, monkeypatch):
    # Flag OFF (default). x-api-key set. A money route (POST /toggle/live) with only x-api-key must NOT be
    # blocked by the operator tier — it flows through to the handler exactly as before (200, not 403).
    client = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    r = client.post("/toggle/live", headers={"x-api-key": "s3cret-key-very-long"}, json={"enabled": False, "confirm": False})
    assert r.status_code != 403, "dark-launch: operator tier must be a no-op when the flag is off"
    assert r.status_code == 200


def test_dark_launch_no_secret_still_open_locally(tmp_path, monkeypatch):
    # No api_secret_key + flag off → the whole gate is a no-op (local dev), byte-identical to today.
    client = _client(tmp_path, monkeypatch)
    assert client.post("/toggle/live", json={"enabled": False, "confirm": False}).status_code == 200


def test_boot_guard_unchanged_when_flag_off():
    # Flag OFF → the new operator boot-assert must NOT fire even in production with no operator secret. Only the
    # pre-existing API_SECRET_KEY assert governs (present here → OK).
    _guard_production_auth(
        SimpleNamespace(environment="production", api_secret_key="k", operator_auth_enforced=False, operator_secret_key=None)
    )  # must not raise


# ── ENFORCED ──────────────────────────────────────────────────────────────────────────────────────────────


def test_enforced_money_route_requires_x_operator(tmp_path, monkeypatch):
    client = _client(
        tmp_path, monkeypatch, secret="api-secret-long", operator_secret="op-secret-long", operator_enforced=True
    )
    hdr = {"x-api-key": "api-secret-long"}
    # money route WITHOUT x-operator → 403 (blocked by the second tier)
    assert client.post("/toggle/live", headers=hdr, json={"enabled": False, "confirm": False}).status_code == 403
    # WITH a wrong x-operator → 403
    assert client.post("/toggle/live", headers={**hdr, "x-operator": "nope"}, json={"enabled": False, "confirm": False}).status_code == 403
    # WITH the right x-operator → passes the gate (200)
    ok = client.post("/toggle/live", headers={**hdr, "x-operator": "op-secret-long"}, json={"enabled": False, "confirm": False})
    assert ok.status_code == 200


def test_enforced_reduce_only_and_reads_unaffected(tmp_path, monkeypatch):
    # A reduce-only SAFETY exit (/ops/killswitch) and a READ (/settings/keys) are NOT money mutations — they
    # need only x-api-key even when enforcement is on (a stop must always route; reads never need a session).
    client = _client(
        tmp_path, monkeypatch, secret="api-secret-long", operator_secret="op-secret-long", operator_enforced=True
    )
    hdr = {"x-api-key": "api-secret-long"}
    # killswitch with confirm=false is a safe no-op but must reach the handler (not 403 from the operator tier)
    ks = client.post("/ops/killswitch", headers=hdr, json={"scope": "all", "confirm": False})
    assert ks.status_code == 200, "reduce-only kill-switch must never be gated by the operator tier"
    assert client.get("/settings/keys", headers=hdr).status_code == 200, "reads never need an operator session"


def test_enforced_but_secret_missing_fails_closed_on_money_route(tmp_path, monkeypatch):
    # Enforcement on but OPERATOR_SECRET_KEY unset → the middleware refuses the money route (fail-closed 403),
    # never silently degrading to one-tier. Reads still work (only money routes are gated).
    client = _client(tmp_path, monkeypatch, secret="api-secret-long", operator_secret=None, operator_enforced=True)
    hdr = {"x-api-key": "api-secret-long"}
    assert client.post("/toggle/live", headers=hdr, json={"enabled": False, "confirm": False}).status_code == 403
    assert client.get("/settings/keys", headers=hdr).status_code == 200


def test_enforced_x_api_key_still_required_first(tmp_path, monkeypatch):
    # The first tier is unchanged: a bad x-api-key is a 401 regardless of the operator header.
    client = _client(
        tmp_path, monkeypatch, secret="api-secret-long", operator_secret="op-secret-long", operator_enforced=True
    )
    assert client.post("/toggle/live", headers={"x-api-key": "wrong", "x-operator": "op-secret-long"}).status_code == 401


# ── BOOT FAIL-CLOSED (second tier) ─────────────────────────────────────────────────────────────────────────


def test_boot_refuses_when_enforced_and_operator_secret_missing():
    with pytest.raises(RuntimeError):
        _guard_production_auth(
            SimpleNamespace(
                environment="production", api_secret_key="k", operator_auth_enforced=True, operator_secret_key=None
            )
        )
    with pytest.raises(RuntimeError):
        _guard_production_auth(
            SimpleNamespace(
                environment="production", api_secret_key="k", operator_auth_enforced=True, operator_secret_key=""
            )
        )


def test_boot_ok_when_enforced_and_operator_secret_present():
    _guard_production_auth(
        SimpleNamespace(environment="production", api_secret_key="k", operator_auth_enforced=True, operator_secret_key="op")
    )  # must not raise
    # non-production leaves both tiers optional even when the flag is on
    _guard_production_auth(
        SimpleNamespace(environment="local", api_secret_key=None, operator_auth_enforced=True, operator_secret_key=None)
    )


# ── CLASSIFIER + NORMALIZATION (must mirror the web) ───────────────────────────────────────────────────────


def test_is_money_mutation_matches_the_money_routes():
    for p in ("/toggle/live", "/live/launch", "/live/defund", "/live/liquidate", "/live/activate", "/live/rules", "/live/jurisdiction", "/ops/breaker/rearm"):
        assert is_money_mutation("POST", p) is True, p


def test_is_money_mutation_excludes_reads_and_safety():
    # reads / reduce-only safety / GET on a money path are NOT money mutations
    assert is_money_mutation("GET", "/toggle/live") is False
    assert is_money_mutation("POST", "/ops/killswitch") is False
    assert is_money_mutation("POST", "/live/orders/abc123/cancel") is False
    assert is_money_mutation("POST", "/overview") is False
    assert is_money_mutation("POST", "/health") is False


def test_normalization_defeats_evasion():
    # trailing slash, double slash, dot segments, case, backslash, and percent-encoding must all normalize to
    # the canonical money path so an attacker can't sidestep the matcher.
    for evil in (
        "/toggle/live/",
        "//toggle//live",
        "/toggle/./live",
        "/live/../toggle/live",
        "/TOGGLE/LIVE",
        "\\toggle\\live",
        "/toggle/%6cive",  # %6c = 'l'
        "/%2e/toggle/live",  # %2e = '.'
    ):
        assert normalize_path(evil) == "/toggle/live", evil
        assert is_money_mutation("POST", evil) is True, evil
