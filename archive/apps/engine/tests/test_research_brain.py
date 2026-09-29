"""The edge-bearing research fixture yields >=1 survivor (the sleeve-open path end-to-end), the survival model
ORDERS the survivors without vetoing, and GET /research/brain returns the shared snake_case contract shape."""

from __future__ import annotations

import os

from cosmu.config.settings import GateSettings, Settings
from cosmu.knowledge.store import Store
from cosmu.lab.research import run_research_pass


def _store(tmp_path) -> Store:
    # The edge-bearing fixture is a strong uptrend (holding the basket out-returns any long-only strategy), so the
    # separate beat-buy-and-hold gate (covered by test_beat_buy_and_hold.py) would block the sleeve-open path this
    # test exercises. Opt it out; the deterministic statistical gate (DSR/PBO/FDR/holdout) still decides survival.
    return Store(
        Settings(
            database_url=f"sqlite:///{tmp_path}/brain.sqlite3",
            openrouter_api_key=None,
            gates=GateSettings(require_beat_buy_and_hold=False),
        )
    )


def test_edge_bearing_fixture_yields_survivor(tmp_path):
    report = run_research_pass(_store(tmp_path), n=6, seed=7, edge_market=True)
    # the deterministic gate (out of any LLM path) opened at least one sleeve
    assert report.cohort.passed >= 1
    assert len(report.survivors) >= 1
    for s in report.survivors:
        assert s.passed
        assert 0.0 <= s.survival_score <= 1.0
        # the survivor proved positive PnL in at least one regime (its live-eligibility passport)
        assert s.proven_regimes


def test_survival_orders_survivors_without_vetoing(tmp_path):
    report = run_research_pass(_store(tmp_path), n=6, seed=7, edge_market=True)
    survivors = report.survivors
    # ranking is a permutation of survivors (no veto): same set, ordered by survival score descending
    scores = [s.survival_score for s in survivors]
    assert scores == sorted(scores, reverse=True)
    # every survivor still carries the gate's PASS — the model changed only the ORDER, not who passed
    assert all(s.passed for s in survivors)


def test_research_pass_persists_event(tmp_path):
    store = _store(tmp_path)
    run_research_pass(store, n=4, seed=7, edge_market=True)
    row = store.row("SELECT payload FROM events WHERE kind = 'research_pass' ORDER BY id DESC LIMIT 1")
    assert row is not None  # the pass is persisted (not CLI-only) so the API can read it


def test_get_research_brain_shape(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.sqlite3")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    # rebuild the cached settings + store the app module bound at import time
    import importlib

    import cosmu.config.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    import cosmu.api.app as app_mod

    importlib.reload(app_mod)

    with TestClient(app_mod.app) as client:
        resp = client.get("/research/brain")
        assert resp.status_code == 200
        body = resp.json()

    # exact shared-contract top-level keys
    assert set(body.keys()) == {"llm", "gated", "survivors", "graveyard", "sources", "tools", "regime", "survival_ranking"}
    assert body["llm"] in ("on", "off")
    assert set(body["gated"].keys()) == {"generated", "passed", "killed", "kill_rate"}
    assert set(body["regime"].keys()) == {"label", "vol_bucket", "trend"}
    for s in body["survivors"]:
        assert set(s.keys()) == {"version_id", "name", "net_pct", "survival_score"}
    for g in body["graveyard"]:
        assert set(g.keys()) == {"name", "reasons"}
    for src in body["sources"]:
        assert set(src.keys()) == {"name", "kind", "low_confidence"}
    for r in body["survival_ranking"]:
        assert set(r.keys()) == {"version_id", "name", "score", "trained"}
    assert isinstance(body["tools"], list) and body["tools"]
    # the OSINT air-activity source is surfaced as a low-confidence source
    osint = [s for s in body["sources"] if s["name"] == "osint_air_activity"]
    assert osint and osint[0]["low_confidence"] is True
