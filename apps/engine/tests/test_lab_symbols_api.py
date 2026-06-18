# GET /lab/symbols serves the per-symbol backtest cells — one row per (strategy × symbol × venue), the granular
# truth the pooled leaderboard averages away. It must: outlier-sort (highest standalone return first), carry the
# honest verdict (so a fragile best-of-N winner is flagged, never celebrated), expose the distinct symbols/venues
# for filter chips, and honour symbol/venue/verdict filters. Read-only, offline, honest empty state.

from __future__ import annotations

import cosmu.api.routers.lab as lab_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store


def _store(tmp_path, name="lab_sym_api") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(lab_mod, "store", store)
    return TestClient(app_mod.app)


def _seed_cell(store: Store, *, name: str, symbol: str, venue: str, return_pct: float, verdict: str,
               trades: int = 40, kind: str = "quant", status: str = "screened",
               oos_return: str = "0.1") -> tuple[str, str]:
    """Persist one (strategy → version → backtest → backtest_symbols) chain the way the finder/loop do.
    Returns (strategy_id, version_id) so the triplet/comparison tests can address the seeded algo + version."""
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": status, "kind": kind, "created_at": "2026-06-17T00:00:00Z",
    })
    bt_id = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": oos_return, "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": trades, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z",
    })
    store.insert("backtest_symbols", {
        "backtest_id": bt_id, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": str(return_pct), "sharpe": "1.2", "max_drawdown": "0.08", "trades": trades,
        "verdict": verdict, "created_at": "2026-06-17T00:00:00Z",
    })
    return sid, vid


def test_honest_empty_state(tmp_path, monkeypatch):
    """No cells yet → empty rows + empty filter lists. Never fabricated."""
    body = _client(monkeypatch, _store(tmp_path)).get("/lab/symbols").json()
    assert body["rows"] == [] and body["symbols"] == [] and body["venues"] == []


def test_outlier_sorted_with_verdict_and_filter_lists(tmp_path, monkeypatch):
    """Cells come back highest standalone return FIRST (the snipe order), each carrying its honest verdict; the
    distinct symbols + venues populate the filter chips."""
    store = _store(tmp_path)
    _seed_cell(store, name="A", symbol="ETHUSDT", venue="binance", return_pct=0.05, verdict="negative")
    _seed_cell(store, name="B", symbol="BTCUSDT", venue="binance", return_pct=0.42, verdict="fragile")
    _seed_cell(store, name="C", symbol="SOLUSDT", venue="hyperliquid", return_pct=0.18, verdict="robust")
    body = _client(monkeypatch, store).get("/lab/symbols").json()
    rows = body["rows"]
    assert [r["symbol"] for r in rows] == ["BTCUSDT", "SOLUSDT", "ETHUSDT"]  # 0.42 > 0.18 > 0.05
    assert rows[0]["verdict"] == "fragile" and rows[0]["return_pct"] == 0.42  # lone winner flagged, not celebrated
    assert body["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert body["venues"] == ["binance", "hyperliquid"]


def test_filters_by_symbol_venue_verdict(tmp_path, monkeypatch):
    """symbol / venue / verdict query params narrow the result set (each in SQL, index-backed)."""
    store = _store(tmp_path)
    _seed_cell(store, name="A", symbol="BTCUSDT", venue="binance", return_pct=0.30, verdict="robust")
    _seed_cell(store, name="B", symbol="BTCUSDT", venue="hyperliquid", return_pct=0.20, verdict="fragile")
    _seed_cell(store, name="C", symbol="ETHUSDT", venue="binance", return_pct=0.10, verdict="robust")
    client = _client(monkeypatch, store)

    by_symbol = client.get("/lab/symbols?symbol=BTCUSDT").json()["rows"]
    assert {r["symbol"] for r in by_symbol} == {"BTCUSDT"} and len(by_symbol) == 2

    by_venue = client.get("/lab/symbols?venue=hyperliquid").json()["rows"]
    assert {r["venue_id"] for r in by_venue} == {"hyperliquid"} and len(by_venue) == 1

    by_verdict = client.get("/lab/symbols?verdict=robust").json()["rows"]
    assert {r["verdict"] for r in by_verdict} == {"robust"} and len(by_verdict) == 2


def test_dedup_keeps_latest_backtest_per_version_symbol(tmp_path, monkeypatch):
    """A re-run fans out a second backtest for the same (version, symbol, venue). The endpoint keeps ONE cell —
    the latest — so the leaderboard never double-counts a single edge."""
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "R", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "R"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    for ts, ret in [("2026-06-17T00:00:00Z", 0.10), ("2026-06-17T01:00:00Z", 0.25)]:
        bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": ts})
        store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": "binance", "return_pct": str(ret), "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "robust", "created_at": ts})
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert len(rows) == 1
    assert rows[0]["return_pct"] == 0.25  # the later re-run, not the earlier 0.10


def test_two_venues_same_version_symbol_are_distinct_cells(tmp_path, monkeypatch):
    """The venue-aware dedup fix: the SAME version on the SAME symbol at TWO venues is TWO cells (the fee axis
    differs) — never collapsed into one. The old (version, symbol) key hid one venue's P&L behind its sibling's."""
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "V", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "V"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z"})
    for venue, ret in [("binance", 0.20), ("hyperliquid", 0.05)]:
        store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": venue, "return_pct": str(ret), "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "robust", "created_at": "2026-06-17T00:00:00Z"})
    rows = _client(monkeypatch, store).get("/lab/symbols?symbol=BTCUSDT").json()["rows"]
    assert len(rows) == 2
    assert {r["venue_id"] for r in rows} == {"binance", "hyperliquid"}


def test_version_id_filter_narrows_to_one_version(tmp_path, monkeypatch):
    """?version_id= narrows to a single Version's cells — what the fiche/comparison plumbing relies on."""
    store = _store(tmp_path)
    _, vid_a = _seed_cell(store, name="A", symbol="BTCUSDT", venue="binance", return_pct=0.30, verdict="robust")
    _seed_cell(store, name="B", symbol="ETHUSDT", venue="binance", return_pct=0.10, verdict="robust")
    client = _client(monkeypatch, store)
    assert len(client.get("/lab/symbols").json()["rows"]) == 2
    only = client.get(f"/lab/symbols?version_id={vid_a}").json()["rows"]
    assert {r["strategy_version_id"] for r in only} == {vid_a}
    assert {r["symbol"] for r in only} == {"BTCUSDT"}


def _seed_cell_less_version(store: Store, *, name: str, status: str = "screened") -> str:
    """An AUTHORED version with NO backtest_symbols cell (no backtest at all). Returns version_id."""
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    return store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": status, "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })


def test_cell_less_versions_surface_as_new_rows(tmp_path, monkeypatch):
    """Item 6: an authored-but-UNCOMPUTED version (no backtest_symbols cell) must surface as a synthetic 'New' row
    — symbol empty, metrics zeroed, its own status carried — so the whole authored population is visible, not just
    versions that have cells."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    new_vid = _seed_cell_less_version(store, name="JustAuthored", status="screened")
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    # The computed cell ranks first; the cell-less version is appended as a New row.
    assert any(r["symbol"] == "BTCUSDT" for r in rows)
    new_rows = [r for r in rows if r["strategy_version_id"] == new_vid]
    assert len(new_rows) == 1
    nr = new_rows[0]
    assert nr["symbol"] == "" and nr["venue_id"] is None        # no cell → no symbol/venue
    assert nr["return_pct"] == 0.0 and nr["trades"] == 0          # nothing computed → zeroed, never fabricated
    assert nr["verdict"] is None
    assert nr["strategy_name"] == "JustAuthored"


def test_cell_less_versions_excluded_when_symbol_filtered(tmp_path, monkeypatch):
    """A symbol/venue/verdict filter is asking for CELLS — a not-yet-computed version (no symbol) is not added."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    _seed_cell_less_version(store, name="JustAuthored")
    rows = _client(monkeypatch, store).get("/lab/symbols?symbol=BTCUSDT").json()["rows"]
    assert {r["symbol"] for r in rows} == {"BTCUSDT"}  # no empty-symbol New row leaks into a filtered view


def test_cell_less_version_appears_after_computed_cells(tmp_path, monkeypatch):
    """New rows are appended AFTER the outlier-ranked computed cells (they carry no return to rank by)."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="ETHUSDT", venue="binance", return_pct=0.33, verdict="robust")
    new_vid = _seed_cell_less_version(store, name="JustAuthored")
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert rows[0]["symbol"] == "ETHUSDT"                 # computed cell first
    assert rows[-1]["strategy_version_id"] == new_vid     # New row last


def test_pooled_return_is_advisory_not_an_average_of_cells(tmp_path, monkeypatch):
    """pooled_return_pct carries the PARENT backtest's pooled OOS return (advisory), distinct from the cell's own
    standalone return_pct — it is NEVER an average of the per-symbol cells."""
    store = _store(tmp_path)
    _seed_cell(store, name="A", symbol="BTCUSDT", venue="binance", return_pct=0.42, verdict="fragile", oos_return="0.07")
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["return_pct"] == 0.42       # the granular truth on THIS cell
    assert row["pooled_return_pct"] == 0.07  # the parent backtest's pooled number, NOT 0.42
