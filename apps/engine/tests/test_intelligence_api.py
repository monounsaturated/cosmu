# GET /intelligence serves the system-intelligence snapshot ("is the machine getting smarter?"): a
# cross-source aggregation over strategy_versions, backtests, research_notes, events and alt_data. That
# recompute is SLOW on prod Postgres (two full-table scans → ~24s) and timed out the 5s SSR fetch, so the
# handler now serves a short-TTL process cache of the LAST really-computed snapshot — never fabricated,
# and an honest-empty result on a fresh store. OFFLINE only: seed a sqlite store, assert correctness, and
# assert the cache keeps the heavy compute OFF the hot path.

from __future__ import annotations

import cosmu.api.intelligence as intel_mod
import cosmu.api.routers.intelligence as intelligence_router
from cosmu.api.intelligence import compute_intelligence, reset_cache
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _store(tmp_path, name="intel_api") -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))
    store.migrate()
    return store


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(intelligence_router, "store", store)
    return TestClient(app_mod.app)


def test_honest_empty_state_on_fresh_store(tmp_path):
    """A brand-new store has nothing learned yet — every count is 0, every list empty. Never fabricated."""
    reset_cache()
    body = compute_intelligence(_store(tmp_path), use_cache=False)

    assert body["funnel"] == {
        "authored": 0, "screened": 0, "gate_passed": 0, "funded": 0, "live": 0, "killed": 0,
    }
    assert body["memory"]["total"] == 0
    assert body["data_freshness"] == []  # no alt_data ingested yet → honest empty, not a stub row
    assert body["ticks"]["total"] == 0 and body["ticks"]["recent"] == []
    assert body["lineage"]["by_origin"] == [] and body["lineage"]["by_operator"] == []
    assert body["regime_coverage"]["covered"] == 0  # 3x3 grid present, but no strategy occupies a cell
    assert len(body["regime_coverage"]["grid"]) == 9


def test_real_data_flows_through_uncached(tmp_path):
    """Seed events + alt_data + research_notes and confirm the snapshot reflects them (no cache)."""
    reset_cache()
    store = _store(tmp_path)
    with store.batch() as w:
        w.append_event(actor="autonomy", kind="autonomy_tick_completed",
                       payload={"summary": {"authored": 10, "gated_passed": 2, "funded": 1}})
        w.append_event(actor="autonomy", kind="autonomy_tick_completed",
                       payload={"summary": {"authored": 8, "gated_passed": 4, "funded": 0}})
        w.insert("research_notes", {"id": "n1", "kind": "dead_end", "body_md": "b", "structured": "{}",
                                    "created_at": "2026-01-01T00:00:00Z"})
        w.insert("research_notes", {"id": "n2", "kind": "winner", "body_md": "b", "structured": "{}",
                                    "created_at": "2026-01-02T00:00:00Z"})
        w.execute(
            "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("funding", "BTCUSDT", "rate", "2026-06-01T00:00:00Z", "2026-06-01T00:05:00Z", 0.01,
             "2026-06-01T00:05:00Z"),
        )
        w.execute(
            "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("funding", "BTCUSDT", "rate", "2026-06-02T00:00:00Z", "2026-06-02T00:05:00Z", 0.02,
             "2026-06-02T00:05:00Z"),
        )

    body = compute_intelligence(store, use_cache=False)

    assert body["ticks"]["total"] == 2
    assert body["ticks"]["total_authored"] == 18 and body["ticks"]["total_survivors"] == 6
    assert body["memory"]["dead_ends"] == 1 and body["memory"]["winners"] == 1
    fresh = {d["source"]: d for d in body["data_freshness"]}
    assert fresh["funding"]["points"] == 2
    assert fresh["funding"]["last_at"] == "2026-06-02T00:05:00Z"  # MAX(available_at), honest


def test_ttl_cache_keeps_heavy_compute_off_the_request_path(tmp_path, monkeypatch):
    """The fix: the slow cross-source aggregation runs at most once per TTL window; repeat calls reuse it."""
    reset_cache()
    store = _store(tmp_path)

    calls = {"n": 0}
    real_compute = intel_mod._compute

    def _counting(s):
        calls["n"] += 1
        return real_compute(s)

    monkeypatch.setattr(intel_mod, "_compute", _counting)

    first = compute_intelligence(store)
    second = compute_intelligence(store)
    third = compute_intelligence(store)

    assert calls["n"] == 1  # only the cold request paid the aggregation cost
    assert first == second == third  # the cache returns the SAME real snapshot, never re-fabricated

    reset_cache()
    compute_intelligence(store)
    assert calls["n"] == 2  # a fresh window recomputes (so the read-out can't go stale forever)


def test_router_serves_the_snapshot_and_is_honest_empty(tmp_path, monkeypatch):
    """End-to-end through FastAPI: the GET returns a valid IntelligenceResponse with honest-empty data."""
    reset_cache()
    body = _client(monkeypatch, _store(tmp_path)).get("/intelligence").json()
    assert body["funnel"]["authored"] == 0
    assert body["data_freshness"] == []
    assert body["memory"]["total"] == 0
    reset_cache()  # leave no cross-test residue
