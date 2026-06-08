# GET /mind and GET /mind/source-trust must serve PRECOMPUTED / CACHED reasoning — never compute it live in the
# request path. On prod /mind hung 35 s (a synchronous Binance regime fetch inside the handler) and
# /mind/source-trust took 23 s (a full-table aggregation per request). The fix: /mind serves the last persisted
# mind_reflections row (the autonomy tick does the live regime read + judge out of band), falling back to an
# OFFLINE deterministic rebuild when none exists; /mind/source-trust is served from a short in-process TTL cache.
# These tests run under conftest's network guard: ANY real socket the handler opens fails the test — so they
# PROVE the request path is offline. Read-only, honest-empty preserved, never fabricated.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import cosmu.api.routers.mind as mind_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind import reflect


def _store(tmp_path, name="mind_api") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_metric(store: Store, metric: str, value: float, *, provider: str = "test", days_ago: int = 0) -> None:
    ts = datetime.now(UTC) - timedelta(days=days_ago)
    store.rows(
        "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider, "BTCUSDT", metric, ts.isoformat(), ts.isoformat(), value, utcnow()),
    )


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(mind_mod, "store", store)
    # Reset the source-trust TTL cache so each test computes fresh against ITS store (no cross-test bleed).
    mind_mod._source_trust_cache["rows"] = None
    mind_mod._source_trust_cache["at"] = 0.0
    return TestClient(app_mod.app)


def test_mind_serves_last_persisted_reflection_offline(tmp_path, monkeypatch):
    """/mind returns the most recent persisted reflection — no live market fetch, no LLM. (If the handler tried
    to reach Binance/an LLM, the network guard would fail this test.)"""
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 15.0)  # extreme fear → bullish consensus, deterministically
    reflect(store)  # the autonomy tick's persistence step — writes the full snapshot to mind_reflections

    body = _client(monkeypatch, store).get("/mind").json()
    assert body["consensus"] == "bullish"
    assert body["railguard"]
    # The persisted snapshot round-trips exactly: the seeded sentiment reads as ingested in KNOWS.
    sentiment = next(l for l in body["knows"] if l["perspective"] == "Sentiment")
    fg = next(i for i in sentiment["items"] if i["name"] == "fear_greed")
    assert fg["ingested"] is True and fg["value"] == 15.0


def test_mind_serves_the_NEWEST_reflection_not_an_old_one(tmp_path, monkeypatch):
    """Two reflections persisted; /mind serves the latest (id DESC), so the read reflects current thinking."""
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 85.0)  # greed → bearish
    reflect(store)
    # Flip the world to extreme fear and reflect again — the newest row must win.
    store.rows("DELETE FROM alt_data")
    _seed_metric(store, "fear_greed", 10.0)  # fear → bullish
    reflect(store)

    body = _client(monkeypatch, store).get("/mind").json()
    assert body["consensus"] == "bullish"


def test_mind_cold_start_rebuilds_offline_and_honest(tmp_path, monkeypatch):
    """No reflection persisted yet → offline deterministic rebuild. With NO reference bars the technical analyst
    abstains honestly and nothing is fabricated; the handler still touches no network."""
    store = _store(tmp_path)
    body = _client(monkeypatch, store).get("/mind").json()
    assert body["consensus"] == "neutral" and body["conviction"] == 0.0
    market = [s for s in body["stances"] if s["kind"] == "market"]
    assert market and all(s["lean"] == "abstain" for s in market)
    assert body["knows"], "cold start still enumerates what it COULD know"


def test_mind_falls_back_when_reflections_table_absent(tmp_path, monkeypatch):
    """A prod DB that hasn't applied the additive mind_reflections migration must not 500 — fall back to the
    offline rebuild rather than erroring."""
    store = _store(tmp_path)
    store.rows("DROP TABLE mind_reflections")
    resp = _client(monkeypatch, store).get("/mind")
    assert resp.status_code == 200
    assert resp.json()["railguard"]


def test_source_trust_honest_empty_state(tmp_path, monkeypatch):
    """No alt-data ingested → every source shows status 'no data', trust 0 — never a fabricated freshness."""
    store = _store(tmp_path)
    body = _client(monkeypatch, store).get("/mind/source-trust").json()
    assert body["rows"], "the scoreboard still enumerates every registered source"
    assert all(r["trust_score"] == 0.0 and r["status"] == "no data" for r in body["rows"])


def test_source_trust_reflects_ingested_freshness(tmp_path, monkeypatch):
    """An ingested source reads as fresh with a non-zero trust score (honest, computed from real data)."""
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 50.0, provider="alternative.me")  # fresh now
    body = _client(monkeypatch, store).get("/mind/source-trust").json()
    fg_source = next(r for r in body["rows"] if r["source"] == "alternative.me")
    assert fg_source["status"] == "fresh" and fg_source["trust_score"] > 0.0


def test_source_trust_is_cached_within_ttl(tmp_path, monkeypatch):
    """The heavy aggregation runs once per TTL: a second request inside the window serves the cached rows and
    does NOT re-query the store (proven by mutating the store and seeing the cached answer unchanged)."""
    store = _store(tmp_path)
    client = _client(monkeypatch, store)
    first = client.get("/mind/source-trust").json()
    assert all(r["status"] == "no data" for r in first["rows"])  # empty store → all no-data
    # Ingest a fresh metric AFTER the first call. Within the TTL the cached (all-no-data) answer must persist.
    _seed_metric(store, "fear_greed", 50.0, provider="alternative.me")
    second = client.get("/mind/source-trust").json()
    fg = next(r for r in second["rows"] if r["source"] == "alternative.me")
    assert fg["status"] == "no data", "served from cache within TTL — not recomputed per request"
    # Expire the cache → the next request recomputes and now sees the fresh ingest.
    mind_mod._source_trust_cache["at"] = 0.0
    third = client.get("/mind/source-trust").json()
    fg3 = next(r for r in third["rows"] if r["source"] == "alternative.me")
    assert fg3["status"] == "fresh"
