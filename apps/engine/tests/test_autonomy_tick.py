"""The AUTONOMOUS MASTER TICK + human-overview API, fully offline:
- one tick runs end-to-end (ingest → author → DETERMINISTIC gate → fund the PAPER Wallet → emit recommendations),
  is audited to the events ledger, and is PAPER-ONLY (no live order, live toggle stays off),
- the tick is idempotent: paused → a no-op; a re-run is clean + audited,
- pause/resume flip the persisted state and gate the tick,
- the LLM seam is injectable and PROPOSES only — the deterministic gate still disposes,
- /autonomy/status shape + counts, /autonomy/pause /resume /tick, /recommendations approve + dismiss.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.scheduler import autonomy_status, is_paused, pause, run_tick


def _store(tmp_path, *, key: str | None = None) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/tick.sqlite3", openrouter_api_key=key))


def _no_ingest(_store) -> dict:
    # Deterministic offline ingest stand-in so the tick never touches the network.
    return {"funding_rate": 3, "fear_greed": 1, "dead_source": 0}


def test_one_tick_runs_end_to_end_paper_only_and_audited(tmp_path):
    store = _store(tmp_path)
    report = run_tick(store, n=6, seed=7, edge_market=True, ingest=_no_ingest)

    # Authored → gated → funded → recommended, all in one bounded cycle.
    assert report.summary.authored == 6
    assert report.summary.gated_passed >= 1
    assert report.summary.funded >= 1
    assert report.summary.recommendations >= 1
    assert report.skipped is False

    # PAPER ONLY: live never armed by the tick.
    assert report.live_enabled is False
    live = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    assert not (live and live["enabled"])
    # No live-routed execution event was emitted (the order path only fills paper).
    routed = store.rows("SELECT id FROM events WHERE kind = 'order_submitted_live'")
    assert routed == []

    # Audited: start + complete markers with the summary on the ledger.
    completed = store.row("SELECT payload FROM events WHERE kind = 'autonomy_tick_completed' ORDER BY id DESC LIMIT 1")
    assert completed is not None
    payload = json.loads(completed["payload"]) if isinstance(completed["payload"], str) else completed["payload"]
    assert payload["summary"]["authored"] == 6
    assert payload["live_enabled"] is False

    # A funded paper position exists (the Wallet was actually funded, no fabricated numbers).
    pos = store.row("SELECT id FROM positions WHERE CAST(qty AS REAL) != 0 LIMIT 1")
    assert pos is not None


def test_tick_is_idempotent_when_paused(tmp_path):
    store = _store(tmp_path)
    pause(store)
    assert is_paused(store) is True
    report = run_tick(store, n=4, seed=7, edge_market=True, ingest=_no_ingest)
    assert report.skipped is True
    assert report.skip_reason == "paused"
    # A paused tick writes NO completed marker (it is a true no-op for the cycle).
    assert store.row("SELECT id FROM events WHERE kind = 'autonomy_tick_completed'") is None


def test_pause_resume_state_machine(tmp_path):
    store = _store(tmp_path)
    assert is_paused(store) is False  # cold start: armed/running
    pause(store)
    assert autonomy_status(store).paused is True
    assert autonomy_status(store).running is False
    from cosmu.master.scheduler import resume

    resume(store)
    assert autonomy_status(store).paused is False
    assert autonomy_status(store).running is True


def test_llm_seam_proposes_but_gate_still_disposes(tmp_path):
    # Inject a mock LLM seam: the tick uses it to PROPOSE structure, but the deterministic gate decides survival.
    store = _store(tmp_path, key="sk-test")

    def chat(_model_id, _prompt):
        return json.dumps({"base_template": "momentum", "features": ["ret_Nd", "adx"], "bar_size": "1d"})

    report = run_tick(store, n=4, seed=7, edge_market=True, ingest=_no_ingest, chat=chat)
    assert report.summary.authored == 4
    # The gate (not the LLM) decided who passed — recorded honestly on the research_pass event.
    rp = store.row("SELECT payload FROM events WHERE kind = 'research_pass' ORDER BY id DESC LIMIT 1")
    payload = json.loads(rp["payload"]) if isinstance(rp["payload"], str) else rp["payload"]
    assert payload["llm"] == "on"
    assert payload["passed"] == report.summary.gated_passed


def test_cycles_run_increments(tmp_path):
    store = _store(tmp_path)
    assert autonomy_status(store).cycles_run == 0
    run_tick(store, n=4, seed=7, edge_market=True, ingest=_no_ingest)
    run_tick(store, n=4, seed=8, edge_market=True, ingest=_no_ingest)
    assert autonomy_status(store).cycles_run == 2


# ---- API surface ----


def _client(tmp_path, monkeypatch) -> TestClient:
    import cosmu.api.app as app_module

    store = _store(tmp_path)
    monkeypatch.setattr(app_module, "store", store)
    return TestClient(app_module.app)


def test_autonomy_status_shape(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/autonomy/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "running",
        "paused",
        "live_enabled",
        "cycles_run",
        "last_tick_at",
        "last_action",
        "next_action",
        "last_summary",
    }
    assert set(body["last_summary"].keys()) == {"authored", "gated_passed", "funded", "recommendations"}
    assert body["live_enabled"] is False


def test_autonomy_pause_resume_tick_api(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/autonomy/pause").json() == {"paused": True}
    assert client.get("/autonomy/status").json()["paused"] is True
    assert client.post("/autonomy/resume").json() == {"paused": False}

    tick = client.post("/autonomy/tick").json()
    assert set(tick.keys()) == {"authored", "gated_passed", "funded", "recommendations"}
    assert tick["authored"] >= 1
    # Status now reflects the completed tick.
    status = client.get("/autonomy/status").json()
    assert status["cycles_run"] == 1
    assert status["last_tick_at"] is not None
    # Still paper-only after a tick via the API.
    assert client.get("/autonomy/status").json()["live_enabled"] is False


def test_recommendation_approve_and_dismiss(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # A tick emits recommendations to act on.
    client.post("/autonomy/tick")
    items = client.get("/recommendations").json()["items"]
    assert items
    rec = items[0]
    approve = client.post(f"/recommendations/{rec['id']}/approve").json()
    assert approve["ok"] is True
    # forward_test_promotion_watch is not money-adjacent → applied.
    assert approve["applied"] is True
    # Re-approving is a no-op (already approved).
    again = client.post(f"/recommendations/{rec['id']}/approve").json()
    assert again["ok"] is False

    # Dismiss a different open one if present, else dismiss is still ok=True on an existing rec.
    open_items = [i for i in client.get("/recommendations").json()["items"] if i["state"] == "open"]
    target = open_items[0] if open_items else rec
    dismiss = client.post(f"/recommendations/{target['id']}/dismiss").json()
    assert dismiss["ok"] is True


def test_recommendation_action_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.post("/recommendations/does-not-exist/approve").status_code == 404
    assert client.post("/recommendations/does-not-exist/dismiss").status_code == 404
