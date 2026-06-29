# GET /authority — the proprietary AUTHORITY dashboard served flat and typed: one composite row per account,
# ordered composite DESC with UNTESTED (null composite) accounts last, every nullable metric passed through as
# null (untested ≠ unskilled — never coerced to 0), top_movers JSON re-hydrated, and an honest empty shape
# (rows=[], as_of=null, n_accounts=0) on a not-yet-populated store. AUTH is the app-level shared-secret
# middleware. Offline + deterministic: temp sqlite Store via TestClient, no network, no lifespan.

from __future__ import annotations

import json

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store

_COLUMNS = (
    "account", "platform", "n_calls", "n_resolved", "n_echo", "hit_rate", "base_hit_rate", "brier",
    "brier_skill_score", "calibration_error", "ev", "avg_move_when_right", "avg_lead_days", "consistency",
    "composite", "rank", "percentile", "composite_z", "top_movers", "last_call_ts", "updated_at",
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/authority_api.sqlite3", openrouter_api_key=None, _env_file=None))


def _seed(store: Store, **row) -> None:
    record = {
        "account": "@acct", "platform": "x", "n_calls": 0, "n_resolved": 0, "n_echo": 0,
        "hit_rate": None, "base_hit_rate": None, "brier": None, "brier_skill_score": None,
        "calibration_error": None, "ev": None, "avg_move_when_right": None, "avg_lead_days": None,
        "consistency": None, "composite": None, "rank": None, "percentile": None, "composite_z": None,
        "top_movers": "[]", "last_call_ts": None, "updated_at": "2026-06-01T00:00:00+00:00",
    }
    record.update(row)
    with store.batch() as writer:
        writer.execute(
            f"INSERT INTO authority_scoreboard ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
            tuple(record[c] for c in _COLUMNS),
        )


def _client(store: Store, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=store.settings.database_url, openrouter_api_key=None, api_secret_key=secret, _env_file=None)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app)


def test_empty_panel_is_honest(tmp_path, monkeypatch):
    client = _client(_store(tmp_path), monkeypatch)
    res = client.get("/authority")
    assert res.status_code == 200
    body = res.json()
    assert body == {"as_of": None, "n_accounts": 0, "rows": []}


def test_rows_ordered_composite_desc_untested_last(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed(
        store, account="@sharp", n_calls=12, n_resolved=8, n_echo=1, hit_rate=0.62, base_hit_rate=0.5,
        brier=0.2, brier_skill_score=0.18, calibration_error=0.1, ev=0.34, avg_move_when_right=0.08,
        avg_lead_days=2.5, consistency=0.6, composite=0.71,
        top_movers=json.dumps([{"asset": "BTC", "ts": "2024-03-01T00:00:00+00:00", "direction": "up",
                                "signed_return": 1.2, "payoff": 0.12, "is_echo": False}]),
        last_call_ts="2024-03-01T00:00:00+00:00", updated_at="2026-06-10T12:00:00+00:00",
    )
    _seed(
        store, account="@weak", n_calls=20, n_resolved=15, hit_rate=0.4, base_hit_rate=0.5, ev=-0.1,
        composite=0.12, updated_at="2026-06-09T12:00:00+00:00",
    )
    # UNTESTED: calls on record, none resolved → composite NULL.
    _seed(store, account="@quiet", n_calls=3, updated_at="2026-06-08T12:00:00+00:00")

    client = _client(store, monkeypatch)
    body = client.get("/authority").json()

    assert body["n_accounts"] == 3
    assert [r["account"] for r in body["rows"]] == ["@sharp", "@weak", "@quiet"]
    # null preserved for the untested account — never coerced to 0.
    assert body["rows"][2]["composite"] is None and body["rows"][2]["ev"] is None
    # top_movers re-hydrated.
    assert body["rows"][0]["top_movers"][0]["asset"] == "BTC"
    assert body["rows"][0]["top_movers"][0]["signed_return"] == 1.2
    assert body["as_of"] == "2026-06-10T12:00:00+00:00"


def test_relative_ranking_passes_through(tmp_path, monkeypatch):
    """The relative-standing columns surface typed: rank as int, percentile/z as float, null when unranked."""
    store = _store(tmp_path)
    _seed(store, account="@a", n_calls=10, n_resolved=8, composite=0.7, rank=1, percentile=1.0, composite_z=1.1,
          updated_at="2026-06-10T00:00:00+00:00")
    _seed(store, account="@b", n_calls=10, n_resolved=8, composite=0.3, rank=2, percentile=0.0, composite_z=-1.1,
          updated_at="2026-06-10T00:00:00+00:00")
    _seed(store, account="@u", n_calls=3, updated_at="2026-06-09T00:00:00+00:00")  # untested → unranked

    client = _client(store, monkeypatch)
    rows = {r["account"]: r for r in client.get("/authority").json()["rows"]}

    assert rows["@a"]["rank"] == 1 and rows["@a"]["percentile"] == 1.0 and rows["@a"]["composite_z"] == 1.1
    assert rows["@b"]["rank"] == 2 and rows["@b"]["composite_z"] == -1.1
    assert rows["@u"]["rank"] is None and rows["@u"]["percentile"] is None and rows["@u"]["composite_z"] is None


def test_requires_api_key_when_secret_set(tmp_path, monkeypatch):
    client = _client(_store(tmp_path), monkeypatch, secret="topsecret")
    assert client.get("/authority").status_code == 401
    assert client.get("/authority", headers={"x-api-key": "topsecret"}).status_code == 200
