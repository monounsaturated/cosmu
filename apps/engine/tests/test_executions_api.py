# GET /executions serves the global Trades feed — every execution (paper + live) newest-first, each tagged
# is_paper with its owning strategy joined. The single /trades page renders this one table. It must: order by ts
# DESC, tag paper vs live honestly, join the strategy name, honour the limit clamp, and stay an honest empty list
# when nothing has filled. Read-only, offline — listing a fill never moves money.

from __future__ import annotations

import cosmu.api.routers.executions as exec_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _store(tmp_path, name="exec_api") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(exec_mod, "store", store)
    return TestClient(app_mod.app)


def _seed_version(store: Store, name: str) -> str:
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    return store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "paper", "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })


def _fill(store: Store, vid: str, *, side: str, ts: str, is_paper: int, venue: str = "binance", fee: str = "0.10") -> str:
    rid = store.insert("runs", {"strategy_version_id": vid, "mode": "paper" if is_paper else "live", "venue_id": venue, "seed": 1, "started_at": ts, "status": "completed"})
    return store.insert("executions", {
        "run_id": rid, "strategy_version_id": vid, "instrument_id": "i", "venue_id": venue, "side": side,
        "qty": "2", "price": "100", "fee": fee, "slippage": "0", "order_type": "market", "is_paper": is_paper,
        "ts": ts, "fill_log": "{}",
    })


def test_honest_empty_state(tmp_path, monkeypatch):
    """No fills yet → empty rows, never fabricated."""
    body = _client(monkeypatch, _store(tmp_path)).get("/executions").json()
    assert body["rows"] == []


def test_newest_first_with_strategy_and_paper_live_tag(tmp_path, monkeypatch):
    """Executions come back newest-first, each carrying the strategy NAME and the is_paper tag (paper vs live) so
    the one Trades table separates simulated money from real money."""
    store = _store(tmp_path)
    vid = _seed_version(store, "Momentum")
    _fill(store, vid, side="buy", ts="2026-06-17T01:00:00Z", is_paper=1)
    _fill(store, vid, side="sell", ts="2026-06-17T03:00:00Z", is_paper=0)  # newest
    _fill(store, vid, side="buy", ts="2026-06-17T02:00:00Z", is_paper=1)
    rows = _client(monkeypatch, store).get("/executions").json()["rows"]
    assert [r["ts"] for r in rows] == ["2026-06-17T03:00:00Z", "2026-06-17T02:00:00Z", "2026-06-17T01:00:00Z"]
    assert all(r["strategy_name"] == "Momentum" for r in rows)
    assert rows[0]["is_paper"] is False and rows[0]["side"] == "sell"  # the live fill, newest
    assert rows[1]["is_paper"] is True
    # The joined version id lets the Trades page deep-link to the strategy sheet.
    assert all(r["strategy_version_id"] == vid for r in rows)


def test_fields_are_real_numbers_and_venue(tmp_path, monkeypatch):
    """The numeric/venue fields round-trip as real values (the Trades table renders them directly)."""
    store = _store(tmp_path)
    vid = _seed_version(store, "Carry")
    _fill(store, vid, side="buy", ts="2026-06-17T01:00:00Z", is_paper=1, venue="kraken", fee="0.25")
    row = _client(monkeypatch, store).get("/executions").json()["rows"][0]
    assert row["qty"] == 2.0 and row["price"] == 100.0 and row["fee"] == 0.25
    assert row["venue"] == "kraken"


def test_limit_is_clamped(tmp_path, monkeypatch):
    """`limit` bounds the response so a fat ledger never floods it; clamped to ≥1."""
    store = _store(tmp_path)
    vid = _seed_version(store, "Spammer")
    for h in range(5):
        _fill(store, vid, side="buy", ts=f"2026-06-17T0{h}:00:00Z", is_paper=1)
    rows = _client(monkeypatch, store).get("/executions?limit=2").json()["rows"]
    assert len(rows) == 2
    # limit=0 clamps to 1 (never a divide-by-zero / empty-by-accident).
    assert len(_client(monkeypatch, store).get("/executions?limit=0").json()["rows"]) == 1
