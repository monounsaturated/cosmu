# The 'fiche triplet' + 'table de comparaison' routes make the strategies view granular at the (algo × asset ×
# venue) triplet, never pooled. GET /strategies/{vid}/triplet focuses ONE cell (the clicked triplet); GET
# /strategies/{vid}/comparison returns EVERY cell of the SAME algo (strategy_id) across its assets/venues — one
# row per (version × symbol × venue), each keeping its OWN P&L/verdict (no averaging). Read-only, offline, honest.

from __future__ import annotations

import cosmu.api.routers.strategies as strat_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _store(tmp_path, name="triplet_api") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod
    import cosmu.api.routers.lab as lab_mod

    # The triplet/comparison routes read through the strategies router's store AND reuse the lab router's cell
    # helpers (which close over lab_mod.store) — patch BOTH so every read hits the hermetic test DB.
    monkeypatch.setattr(strat_mod, "store", store)
    monkeypatch.setattr(lab_mod, "store", store)
    return TestClient(app_mod.app)


def _algo(store: Store, name: str) -> str:
    return store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})


def _version(store: Store, strategy_id: str, *, oos_return: str = "0.1") -> tuple[str, str]:
    """A version of an algo + its backtest. Returns (version_id, backtest_id)."""
    vid = store.insert("strategy_versions", {
        "strategy_id": strategy_id, "spec": {"name": "s"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": oos_return, "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z",
    })
    return vid, bt


def _cell(store: Store, vid: str, bt: str, *, symbol: str, venue: str | None, return_pct: float,
          verdict: str = "robust", ts: str = "2026-06-17T00:00:00Z") -> None:
    store.insert("backtest_symbols", {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": str(return_pct), "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": verdict,
        "created_at": ts,
    })


def test_triplet_focuses_the_clicked_cell(tmp_path, monkeypatch):
    """?symbol=&venue= focuses ONE granular cell — the clicked triplet's standalone result, with the parent
    backtest's pooled number carried as advisory only (never the cell's return)."""
    store = _store(tmp_path)
    sid = _algo(store, "A")
    vid, bt = _version(store, sid, oos_return="0.08")
    _cell(store, vid, bt, symbol="BTCUSDT", venue="binance", return_pct=0.30, verdict="robust")
    _cell(store, vid, bt, symbol="ETHUSDT", venue="binance", return_pct=-0.10, verdict="negative")
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/triplet?symbol=BTCUSDT&venue=binance").json()
    assert body["strategy_id"] == sid and body["strategy_version_id"] == vid
    cell = body["cell"]
    assert cell["symbol"] == "BTCUSDT" and cell["venue_id"] == "binance"
    assert cell["return_pct"] == 0.30          # the granular truth
    assert cell["pooled_return_pct"] == 0.08   # advisory pooled, NOT the 0.30 cell


def test_triplet_honest_none_when_no_such_cell(tmp_path, monkeypatch):
    """A triplet with no backtest cell returns cell=None — honest empty, never a fabricated row."""
    store = _store(tmp_path)
    sid = _algo(store, "A")
    vid, bt = _version(store, sid)
    _cell(store, vid, bt, symbol="BTCUSDT", venue="binance", return_pct=0.30)
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/triplet?symbol=DOGEUSDT&venue=binance").json()
    assert body["cell"] is None


def test_triplet_404_for_unknown_version(tmp_path, monkeypatch):
    assert _client(monkeypatch, _store(tmp_path)).get("/strategies/nope/triplet?symbol=X&venue=y").status_code == 404


def test_comparison_returns_every_cell_of_the_same_algo(tmp_path, monkeypatch):
    """The comparison table spans the WHOLE algo (strategy_id) — every version's cells across assets/venues — so
    the fiche can show the clicked cell's siblings side by side. Each cell keeps its own P&L; outlier-sorted."""
    store = _store(tmp_path)
    sid = _algo(store, "A")
    v1, b1 = _version(store, sid)
    v2, b2 = _version(store, sid)  # a second version of the SAME algo
    _cell(store, v1, b1, symbol="BTCUSDT", venue="binance", return_pct=0.30)
    _cell(store, v1, b1, symbol="BTCUSDT", venue="hyperliquid", return_pct=0.12)  # same symbol, other venue
    _cell(store, v2, b2, symbol="ETHUSDT", venue="binance", return_pct=0.05)
    # A DIFFERENT algo's cell must NOT leak into this algo's comparison.
    other = _algo(store, "B")
    vo, bo = _version(store, other)
    _cell(store, vo, bo, symbol="SOLUSDT", venue="binance", return_pct=0.99)

    body = _client(monkeypatch, store).get(f"/strategies/{v1}/comparison").json()
    rows = body["rows"]
    assert len(rows) == 3  # both versions' cells, both venues — never the other algo's
    assert [r["return_pct"] for r in rows] == [0.30, 0.12, 0.05]  # outlier-sorted
    assert {r["strategy_id"] for r in rows} == {sid}
    assert "SOLUSDT" not in {r["symbol"] for r in rows}
    # Distinct symbols/venues drive the asset/venue selector — derived from THIS algo only.
    assert body["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert body["venues"] == ["binance", "hyperliquid"]


def test_comparison_resolves_algo_from_any_version(tmp_path, monkeypatch):
    """Asking from version 2 yields the SAME algo-wide set as asking from version 1 — the table is per-algo."""
    store = _store(tmp_path)
    sid = _algo(store, "A")
    v1, b1 = _version(store, sid)
    v2, b2 = _version(store, sid)
    _cell(store, v1, b1, symbol="BTCUSDT", venue="binance", return_pct=0.30)
    _cell(store, v2, b2, symbol="ETHUSDT", venue="binance", return_pct=0.05)
    client = _client(monkeypatch, store)
    from_v1 = client.get(f"/strategies/{v1}/comparison").json()["rows"]
    from_v2 = client.get(f"/strategies/{v2}/comparison").json()["rows"]
    assert {(r["strategy_version_id"], r["symbol"]) for r in from_v1} == {(r["strategy_version_id"], r["symbol"]) for r in from_v2}


def test_comparison_404_for_unknown_version(tmp_path, monkeypatch):
    assert _client(monkeypatch, _store(tmp_path)).get("/strategies/nope/comparison").status_code == 404
