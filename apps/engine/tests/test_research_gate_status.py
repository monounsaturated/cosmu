# GET /research/gate returns the latest SINGLE-SIGNAL verdict. Since gate_verdicts now also stores cohort
# research verdicts (payload kind='cohort', a different shape), a cohort row landing as the newest row must NOT
# 500 the status card — the GET walks recent rows and returns the first single-signal verdict it can parse.

from __future__ import annotations

import json

import cosmu.api.routers.research as research_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow

_EDGE_PAYLOAD = {
    "decision": "STOP", "passed": False, "best_signal": "btc_social", "deflated_sharpe_prob": 0.42,
    "cscv_pbo": 0.5, "buy_and_hold_return": 0.1, "best_return": 0.05, "regimes_positive": 1,
    "num_trades": 30, "max_drawdown": 0.2, "attempts": 5, "reasons": ["deflated_sharpe"],
    "bar": {}, "data_source": "synthetic", "ts": "2026-06-07T00:00:00+00:00",
}


def _insert(store, decision, data_source, payload):
    store.rows("INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
               (utcnow(), decision, data_source, json.dumps(payload, sort_keys=True)))


def test_gate_status_skips_cohort_row_and_returns_single_signal(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/gs.sqlite3", openrouter_api_key=None))
    monkeypatch.setattr(research_mod, "store", store)

    _insert(store, "STOP", "synthetic", _EDGE_PAYLOAD)                          # older single-signal verdict
    _insert(store, "FAIL", "live", {"kind": "cohort", "run_id": "r1", "source": "x", "passed": False})  # newest = cohort

    resp = TestClient(app_mod.app).get("/research/gate")
    assert resp.status_code == 200            # the cohort row did NOT break the parse
    verdict = resp.json()["verdict"]
    assert verdict is not None and verdict["best_signal"] == "btc_social" and verdict["decision"] == "STOP"


def test_gate_status_null_when_only_cohort_rows(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/gs2.sqlite3", openrouter_api_key=None))
    monkeypatch.setattr(research_mod, "store", store)
    _insert(store, "PASS", "live", {"kind": "cohort", "run_id": "r2", "source": "y", "passed": True})

    resp = TestClient(app_mod.app).get("/research/gate")
    assert resp.status_code == 200 and resp.json()["verdict"] is None   # honest: no single-signal verdict yet
