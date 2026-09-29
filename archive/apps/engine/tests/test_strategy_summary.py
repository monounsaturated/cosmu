# Plain-language summary plumbing: summary_facts assembles DETERMINISTIC facts from existing tables and
# facts_hash pins them; GET /strategies/{id}/summary-facts serves facts+pin (404 unknown); PUT
# /strategies/{id}/summary stores an externally-written summary as a research_notes row kind='summary'
# (latest wins). AUTH is the app-level shared-secret middleware (cosmu/api/app.py): API_SECRET_KEY set →
# EVERY route except /health (the PUT and the GETs here included) requires a matching x-api-key; unset →
# open (local dev). The strategy detail response carries summary_md/summary_stale/summary_updated_at with
# honest nulls and a staleness flip when a metric changes. Offline + deterministic: temp sqlite Store, no
# network, no lifespan — the engine never WRITES summary text.

from __future__ import annotations

import cosmu.api.app as app_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research.summary_facts import facts_hash, summary_facts

SPEC = {
    "rationale": "Buy 4h breakouts above the opening range when funding is calm.",
    "horizon": {"bar_size": "4h", "min_hold_days": 1, "max_hold_days": 5},
    "universe": {"venues": ["binance"], "asset_classes": ["crypto"]},
}


def _store(tmp_path) -> Store:
    # _env_file=None → hermetic: ignore a dev box's .env.local (API_SECRET_KEY there would 401 the
    # no-secret tests), exactly as tests/test_api_keys.py does.
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/summary.sqlite3", openrouter_api_key=None, _env_file=None))


def _seed_version(store: Store, *, status: str = "forward_test", kill_reason: str | None = None, with_track: bool = True) -> str:
    sid = store.insert("strategies", {"name": "ORB Breakout", "thesis": "Range breakouts carry momentum.", "origin": "seed", "created_at": "2026-01-01"})
    vid = store.insert(
        "strategy_versions",
        {"strategy_id": sid, "spec": SPEC, "generated_code": "", "code_hash": "h", "params": {}, "origin": "seed", "status": status, "created_at": "2026-01-01", "kill_reason": kill_reason},
    )
    store.insert(
        "backtests",
        {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.042", "sharpe": "1.1", "sortino": "1.3",
            "deflated_sharpe": "0.31", "max_dd": "0.08", "win_rate": "0.55", "num_trades": 42, "pbo": "0.2",
            "trials_counted": 10, "folds_positive": 3, "passed_gates": 1, "holdout_passed": 1, "created_at": "2026-01-02",
        },
    )
    if with_track:
        store.insert("tracks", {"strategy_version_id": vid, "starting_capital": "100000", "equity": "101500", "return_pct": "1.5", "updated_at": "2026-01-03"})
    return vid


def _client(store: Store, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=store.settings.database_url, openrouter_api_key=None, api_secret_key=secret, _env_file=None)
    # Writes to app_mod.settings/store fan out to _shared + every router (the back-compat seam) — the
    # auth middleware reads _shared.settings at request time, so the injected secret governs it too.
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app)  # no `with` → lifespan/startup backtest does not run


# ── summary_facts + facts_hash (pure, offline, deterministic) ───────────────────────────────────


def test_summary_facts_unknown_version_is_none(tmp_path):
    assert summary_facts(_store(tmp_path), "no-such-version") is None


def test_summary_facts_contents(tmp_path):
    store = _store(tmp_path)
    vid = _seed_version(store)
    facts = summary_facts(store, vid)
    assert facts is not None
    assert facts["name"] == "ORB Breakout" and facts["thesis"] == "Range breakouts carry momentum."
    assert facts["rationale"] == SPEC["rationale"]
    assert facts["lane"] == "seed" and facts["bar_size"] == "4h" and facts["asset_classes"] == ["crypto"]
    assert facts["status"] == "forward_test" and facts["kill_reason"] is None
    assert facts["screen"] == {
        "oos_return": 0.042, "deflated_sharpe": 0.31, "max_dd": 0.08,
        "num_trades": 42, "passed_gates": True, "holdout_passed": True,
    }
    assert facts["forward_test"] == {"return_pct": 1.5, "equity": 101500.0, "starting_capital": 100000.0, "updated_at": "2026-01-03"}


def test_facts_hash_is_deterministic_and_flips_on_metric_change(tmp_path):
    store = _store(tmp_path)
    vid = _seed_version(store)
    first = facts_hash(summary_facts(store, vid))
    assert first == facts_hash(summary_facts(store, vid))  # same rows → same pin, every time
    # A metric change MUST flip the pin — that is the staleness mechanism.
    store.rows("UPDATE backtests SET oos_return = '0.061' WHERE strategy_version_id = ?", (vid,))
    assert facts_hash(summary_facts(store, vid)) != first


def test_summary_facts_honest_none_for_missing_screen_and_track(tmp_path):
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "Bare", "thesis": "t", "origin": "wildcard", "created_at": "2026-01-01"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": SPEC, "generated_code": "", "code_hash": "h", "params": {}, "origin": "wildcard", "status": "killed", "created_at": "2026-01-01", "kill_reason": "deflated_sharpe,fdr"})
    facts = summary_facts(store, vid)
    assert facts["screen"] is None and facts["forward_test"] is None  # never fabricated
    assert facts["lane"] == "explore" and facts["kill_reason"] == "deflated_sharpe,fdr"


# ── GET /strategies/{id}/summary-facts ──────────────────────────────────────────────────────────


def test_get_summary_facts_endpoint(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _seed_version(store)
    c = _client(store, monkeypatch)
    body = c.get(f"/strategies/{vid}/summary-facts").json()
    assert body["facts"]["version_id"] == vid
    assert body["facts_hash"] == facts_hash(summary_facts(store, vid))


def test_get_summary_facts_404_unknown_version(tmp_path, monkeypatch):
    c = _client(_store(tmp_path), monkeypatch)
    assert c.get("/strategies/no-such-version/summary-facts").status_code == 404


# ── PUT /strategies/{id}/summary (auth = the global x-api-key middleware) ──────────────────────


def _put_body(pin: str) -> dict:
    return {"body_md": "This strategy buys breakouts. The gate passed it.", "facts_hash": pin, "model": "claude", "prompt_version": "v1"}


def test_summary_routes_behind_shared_secret_when_set(tmp_path, monkeypatch):
    # API_SECRET_KEY set → the app-level middleware gates EVERY route except /health: the facts GET and
    # the summary PUT both 401 without/with-wrong x-api-key, and unlock with the matching header.
    store = _store(tmp_path)
    vid = _seed_version(store)
    c = _client(store, monkeypatch, secret="s3cret")
    auth = {"x-api-key": "s3cret"}
    assert c.get(f"/strategies/{vid}/summary-facts").status_code == 401  # GETs are gated too
    pin = c.get(f"/strategies/{vid}/summary-facts", headers=auth).json()["facts_hash"]
    assert c.put(f"/strategies/{vid}/summary", json=_put_body(pin)).status_code == 401  # no header
    assert c.put(f"/strategies/{vid}/summary", json=_put_body(pin), headers={"x-api-key": "wrong"}).status_code == 401
    ok = c.put(f"/strategies/{vid}/summary", json=_put_body(pin), headers=auth)
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    row = store.row("SELECT body_md, structured, embedding FROM research_notes WHERE strategy_version_id = ? AND kind = 'summary'", (vid,))
    assert row is not None and "breakouts" in row["body_md"]
    assert row["embedding"]  # serialized like other research_notes rows (deterministic keyless embed)


def test_put_summary_open_when_no_secret_configured(tmp_path, monkeypatch):
    # Engine posture: no API_SECRET_KEY (local dev) → the middleware is a no-op, same as every other route.
    store = _store(tmp_path)
    vid = _seed_version(store)
    c = _client(store, monkeypatch)
    pin = c.get(f"/strategies/{vid}/summary-facts").json()["facts_hash"]
    assert c.put(f"/strategies/{vid}/summary", json=_put_body(pin)).status_code == 200


def test_put_summary_404_unknown_version(tmp_path, monkeypatch):
    c = _client(_store(tmp_path), monkeypatch, secret="s3cret")
    resp = c.put("/strategies/no-such-version/summary", json=_put_body("deadbeef"), headers={"x-api-key": "s3cret"})
    assert resp.status_code == 404


# ── Strategy detail carries the summary (honest nulls · staleness flip · latest wins) ───────────


def test_detail_summary_honest_nulls_when_absent(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _seed_version(store)
    body = _client(store, monkeypatch).get(f"/strategies/{vid}").json()
    assert body["summary_md"] is None and body["summary_stale"] is None and body["summary_updated_at"] is None


def test_detail_summary_fresh_then_stale_when_metric_changes(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _seed_version(store)
    c = _client(store, monkeypatch)
    pin = c.get(f"/strategies/{vid}/summary-facts").json()["facts_hash"]
    assert c.put(f"/strategies/{vid}/summary", json=_put_body(pin)).status_code == 200
    body = c.get(f"/strategies/{vid}").json()
    assert body["summary_md"] and body["summary_stale"] is False and body["summary_updated_at"]
    # The forward test re-marks (equity moves) → the stored pin no longer matches → honestly STALE.
    store.rows("UPDATE tracks SET equity = '99000', return_pct = '-1.0', updated_at = '2026-01-04' WHERE strategy_version_id = ?", (vid,))
    assert c.get(f"/strategies/{vid}").json()["summary_stale"] is True


def test_detail_summary_latest_wins(tmp_path, monkeypatch):
    store = _store(tmp_path)
    vid = _seed_version(store)
    c = _client(store, monkeypatch)
    pin = c.get(f"/strategies/{vid}/summary-facts").json()["facts_hash"]
    assert c.put(f"/strategies/{vid}/summary", json=_put_body(pin)).status_code == 200
    second = {"body_md": "Rewritten: clearer and current.", "facts_hash": pin, "model": "claude", "prompt_version": "v2"}
    assert c.put(f"/strategies/{vid}/summary", json=second).status_code == 200
    body = c.get(f"/strategies/{vid}").json()
    assert body["summary_md"] == "Rewritten: clearer and current."  # the new latest wins
    assert store.row("SELECT COUNT(*) AS n FROM research_notes WHERE strategy_version_id = ? AND kind = 'summary'", (vid,))["n"] == 2
