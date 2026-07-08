# GET /lab/symbols serves the per-symbol backtest cells — one row per (strategy × symbol × venue), the granular
# truth the pooled leaderboard averages away. It must: outlier-sort (highest standalone return first), carry the
# honest verdict (so a fragile best-of-N winner is flagged, never celebrated), expose the distinct symbols/venues
# for filter chips, and honour symbol/venue/verdict filters. Read-only, offline, honest empty state.

from __future__ import annotations

import cosmu.api.routers.lab as lab_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow


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


def test_dedup_keeps_latest_backtest_per_triplet(tmp_path, monkeypatch):
    """A re-run fans out a second backtest for the same (strategy, symbol, venue) triplet. The endpoint keeps ONE
    cell — the latest — so the leaderboard never double-counts a single edge."""
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "R", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "R"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    for ts, ret in [("2026-06-17T00:00:00Z", 0.10), ("2026-06-17T01:00:00Z", 0.25)]:
        bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": ts})
        store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": "binance", "return_pct": str(ret), "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "robust", "created_at": ts})
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert len(rows) == 1
    assert rows[0]["return_pct"] == 0.25  # the later re-run, not the earlier 0.10


def test_dedup_collapses_many_versions_of_one_strategy_on_one_triplet(tmp_path, monkeypatch):
    """FIX 1 — the core triplet fix: ONE strategy with THREE near-identical VERSIONS, each with its own cell on the
    SAME (symbol=SOLUSDT, venue=binance) triplet, must show ONE row — the LATEST version (most recent created_at) —
    NOT three near-duplicate rows, and HONESTLY the latest, NEVER the best-return version (no best-of-N selection)."""
    store = _store(tmp_path)
    sid = store.insert("strategies", {"name": "DeFi-flow risk appetite", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    latest_vid = None
    # Three versions: oldest has the BEST return; newest is created_at-latest with a MIDDLING return. The kept row
    # must be the newest (0.15), proving we keep the LATEST, not the best (0.40).
    for ts, ret in [("2026-06-17T00:00:00Z", 0.40), ("2026-06-17T01:00:00Z", 0.05), ("2026-06-17T02:00:00Z", 0.15)]:
        vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "DeFi-flow risk appetite"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": ts})
        latest_vid = vid
        bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": ts})
        store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "SOLUSDT", "venue_id": "binance", "return_pct": str(ret), "sharpe": "1.2", "max_drawdown": "0.08", "trades": 40, "verdict": "robust", "created_at": ts})
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert len(rows) == 1                                  # ONE row per (strategy, symbol, venue) triplet
    assert rows[0]["strategy_version_id"] == latest_vid    # the LATEST version, not the oldest
    assert rows[0]["return_pct"] == 0.15                   # the latest's return — NEVER the best-of-N 0.40


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


def _seed_track_only_version(store: Store, *, name: str, status: str = "paper", track: bool = True) -> str:
    """A version with NO backtest_symbols cell. When ``track`` it ALSO holds a paper/live track (the armed,
    documented-cohort shape — DAA / ADM / TSMOM); when not, it's a plain cell-less version (e.g. killed graveyard)
    that must NOT surface. The track is seeded HONESTLY (equity = starting_capital, return_pct = 0), mirroring
    master.tracks.open_paper_track. Returns version_id."""
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": status, "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })
    if track:
        store.insert("tracks", {
            "strategy_version_id": vid, "starting_capital": "1000", "equity": "1000.00",
            "return_pct": "0.00", "updated_at": "2026-06-17T00:00:00Z",
        })
    return vid


def test_track_only_strategies_surface_as_rows(tmp_path, monkeypatch):
    """FIX 2: an ARMED strategy (a paper/live track but NO backtest_symbols cell — DAA / ADM / TSMOM, armed via the
    documented-cohort path) must surface as a synthetic row — symbol empty, metrics NULL/zeroed, and crucially its
    REAL status carried (paper, not 'New') — so it's visible on the screener like it is on /paper."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    armed_vid = _seed_track_only_version(store, name="Defensive Asset Allocation", status="paper")
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    # The computed cell ranks first; the track-only armed strategy is appended.
    assert any(r["symbol"] == "BTCUSDT" for r in rows)
    armed = [r for r in rows if r["strategy_version_id"] == armed_vid]
    assert len(armed) == 1
    ar = armed[0]
    assert ar["symbol"] == "" and ar["venue_id"] is None        # no cell → no symbol/venue
    assert ar["return_pct"] == 0.0 and ar["trades"] == 0          # nothing computed per-symbol → never fabricated
    assert ar["verdict"] is None
    assert ar["status"] == "paper"                                # REAL track/version status, not "New"
    assert ar["strategy_name"] == "Defensive Asset Allocation"


def test_cell_less_version_without_a_track_is_hidden(tmp_path, monkeypatch):
    """The noise filter: a cell-less version with NO track (e.g. a killed graveyard version) must NOT flood the
    screener — only track-bearing (paper-tested) strategies are surfaced as synthetic rows."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    ghost_vid = _seed_track_only_version(store, name="KilledGraveyard", status="killed", track=False)
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert all(r["strategy_version_id"] != ghost_vid for r in rows)  # no track → never surfaced


def test_track_only_strategies_excluded_when_symbol_filtered(tmp_path, monkeypatch):
    """A symbol/venue/verdict filter is asking for CELLS — a track-only (no symbol) version is not added."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    _seed_track_only_version(store, name="Accelerating Dual Momentum", status="paper")
    rows = _client(monkeypatch, store).get("/lab/symbols?symbol=BTCUSDT").json()["rows"]
    assert {r["symbol"] for r in rows} == {"BTCUSDT"}  # no empty-symbol track-only row leaks into a filtered view


def test_track_only_strategy_appears_after_computed_cells(tmp_path, monkeypatch):
    """Track-only rows are appended AFTER the outlier-ranked computed cells (they carry no return to rank by)."""
    store = _store(tmp_path)
    _seed_cell(store, name="HasCell", symbol="ETHUSDT", venue="binance", return_pct=0.33, verdict="robust")
    armed_vid = _seed_track_only_version(store, name="Diversified Time-Series Momentum", status="paper")
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    assert rows[0]["symbol"] == "ETHUSDT"                  # computed cell first
    assert rows[-1]["strategy_version_id"] == armed_vid    # track-only row last


def test_strategy_with_both_cells_and_track_is_not_double_counted(tmp_path, monkeypatch):
    """Don't-double-count: a strategy that has BOTH a cell-backed version AND a separate cell-less track version
    appears ONCE (its cell row) — no redundant synthetic track-only row for the same algo."""
    store = _store(tmp_path)
    # One strategy, two versions: v1 has a cell, v2 is a cell-less track. Share the SAME strategy_id.
    sid = store.insert("strategies", {"name": "FundingCarry", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    v1 = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "FundingCarry"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "killed", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    bt = store.insert("backtests", {"strategy_version_id": v1, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z"})
    store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": v1, "symbol": "BTCUSDT", "venue_id": "binance", "return_pct": "0.12", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "robust", "created_at": "2026-06-17T00:00:00Z"})
    v2 = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "FundingCarry"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T01:00:00Z"})
    store.insert("tracks", {"strategy_version_id": v2, "starting_capital": "1000", "equity": "1000.00", "return_pct": "0.00", "updated_at": "2026-06-17T01:00:00Z"})
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    fc = [r for r in rows if r["strategy_id"] == sid]
    assert len(fc) == 1                       # the cell row only — no redundant synthetic row for v2
    assert fc[0]["strategy_version_id"] == v1 and fc[0]["symbol"] == "BTCUSDT"


def test_pooled_return_is_advisory_not_an_average_of_cells(tmp_path, monkeypatch):
    """pooled_return_pct carries the PARENT backtest's pooled OOS return (advisory), distinct from the cell's own
    standalone return_pct — it is NEVER an average of the per-symbol cells."""
    store = _store(tmp_path)
    _seed_cell(store, name="A", symbol="BTCUSDT", venue="binance", return_pct=0.42, verdict="fragile", oos_return="0.07")
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["return_pct"] == 0.42       # the granular truth on THIS cell
    assert row["pooled_return_pct"] == 0.07  # the parent backtest's pooled number, NOT 0.42


# --------------------------------------------------------------------------- Fix 1: confidence lower-bound (SE/CI)


def test_annualized_return_lo_is_a_lower_bound_not_the_point_estimate(tmp_path, monkeypatch):
    """A positive cell exposes return_pct_annualized_lo — a CONSERVATIVE floor STRICTLY BELOW the point CAGR — so
    the screener shows '≥ x%/yr' confidence, never a noisy point estimate as fact. NULL only when too thin/no window."""
    store = _store(tmp_path)
    # A healthy, many-trade cell with a real window so both CAGR and its lower-bound are computable.
    sid = store.insert("strategies", {"name": "LoBound", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": "LoBound"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 120, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "oos_start": "2024-01", "oos_end": "2025-12", "created_at": "2026-06-17T00:00:00Z"})
    store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": "binance", "return_pct": "0.40", "sharpe": "1.5", "max_drawdown": "0.08", "trades": 120, "verdict": "robust", "oos_window_days": 730.0, "created_at": "2026-06-17T00:00:00Z"})
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["return_pct_annualized"] is not None
    assert row["return_pct_annualized_lo"] is not None
    assert row["return_pct_annualized_lo"] < row["return_pct_annualized"]  # the floor sits BELOW the point CAGR
    assert row["return_pct_annualized_lo"] >= 0  # a positive edge's floor never goes negative under the shrinkage


def test_annualized_return_lo_collapses_more_for_a_thin_noisy_cell(tmp_path, monkeypatch):
    """The whole point: a FEW-trade cell shrinks HARD toward 0 (poorly estimated) while a many-trade cell barely
    moves — so two cells with the SAME headline CAGR get DIFFERENT confidence floors (3-trade ≠ 300-trade)."""
    store = _store(tmp_path)

    def _cell(name, trades):
        sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
        vid = store.insert("strategy_versions", {"strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
        bt = store.insert("backtests", {"strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": trades, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "oos_start": "2024-01", "oos_end": "2025-12", "created_at": "2026-06-17T00:00:00Z"})
        store.insert("backtest_symbols", {"backtest_id": bt, "strategy_version_id": vid, "symbol": "BTCUSDT", "venue_id": "binance", "return_pct": "0.40", "sharpe": "1.5", "max_drawdown": "0.08", "trades": trades, "verdict": "robust", "oos_window_days": 730.0, "created_at": "2026-06-17T00:00:00Z"})
        return vid

    thin_vid = _cell("Thin", trades=3)
    fat_vid = _cell("Fat", trades=300)
    rows = _client(monkeypatch, store).get("/lab/symbols").json()["rows"]
    thin = next(r for r in rows if r["strategy_version_id"] == thin_vid)
    fat = next(r for r in rows if r["strategy_version_id"] == fat_vid)
    # Same point CAGR (same return + window), but the thin cell's confidence floor is FAR lower than the fat one's.
    assert thin["return_pct_annualized"] == fat["return_pct_annualized"]
    assert thin["return_pct_annualized_lo"] < fat["return_pct_annualized_lo"]


def test_annualized_return_lo_is_null_without_a_window(tmp_path, monkeypatch):
    """No OOS window (legacy cell) → can't annualize at all → both the point CAGR and its lower-bound are null
    (honest "—"), never a fabricated floor."""
    store = _store(tmp_path)
    _seed_cell(store, name="NoWindow", symbol="BTCUSDT", venue="binance", return_pct=0.40, verdict="robust")
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["return_pct_annualized"] is None
    assert row["return_pct_annualized_lo"] is None


# --------------------------------------------------------------------------- Fix 2: thin-sample flag


# --------------------------------------------------------------------------- has_paper_fills (honest "Paper" badge)


def _add_paper_fill(store: Store, vid: str, *, venue: str = "binance", is_paper: int = 1) -> None:
    """Record ONE real fill in the executions ledger — the signal that makes has_paper_fills True (the SAME
    is_paper=1 signal the leaderboard/detail-sheet read). The web keys the 'Paper' BADGE off this so a paper-status
    row with NO fill reads 'Backtest', not 'Paper'."""
    rid = store.insert("runs", {"strategy_version_id": vid, "mode": "paper", "venue_id": venue, "seed": 1, "started_at": utcnow(), "status": "completed"})
    store.insert("executions", {
        "run_id": rid, "strategy_version_id": vid, "instrument_id": "i", "venue_id": venue, "side": "buy",
        "qty": "1", "price": "100", "fee": "0.1", "slippage": "0", "order_type": "market", "is_paper": is_paper,
        "ts": utcnow(), "fill_log": "{}",
    })


def test_has_paper_fills_true_when_a_paper_fill_exists(tmp_path, monkeypatch):
    """A paper-status cell whose version has a real is_paper=1 fill carries has_paper_fills=True — so the web's
    isPaperRow predicate badges it 'Paper' honestly."""
    store = _store(tmp_path)
    _, vid = _seed_cell(store, name="Traded", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust", status="paper")
    _add_paper_fill(store, vid)
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["has_paper_fills"] is True


def test_has_paper_fills_false_for_a_no_fill_watch_lane_reject(tmp_path, monkeypatch):
    """The badge-truth fix: a PAPER-status cell with NO fill (a zero-capital watch-lane reject) carries
    has_paper_fills=False — the input the web uses to badge it 'Backtest', not 'Paper'."""
    store = _store(tmp_path)
    _seed_cell(store, name="WatchReject", symbol="ETHUSDT", venue="binance", return_pct=0.05, verdict="negative", status="paper")
    row = _client(monkeypatch, store).get("/lab/symbols").json()["rows"][0]
    assert row["status"] == "paper"          # overloaded status still says paper…
    assert row["has_paper_fills"] is False   # …but no fill → the web badges it Backtest


# --------------------------------------------------------------------------- fee_bps (stage-aware fees column)


def test_fee_bps_is_the_venue_taker_fee(tmp_path, monkeypatch):
    """Each cell carries its venue's TODAY taker fee (fees-always-today) so the screener's Fees column is real,
    never fabricated. binance taker = 10 bps in the catalog; an unknown venue is honest None."""
    store = _store(tmp_path)
    _seed_cell(store, name="Binance", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust")
    _seed_cell(store, name="Bogus", symbol="ETHUSDT", venue="not_a_real_venue", return_pct=0.10, verdict="robust")
    rows = {r["strategy_name"]: r for r in _client(monkeypatch, store).get("/lab/symbols").json()["rows"]}
    assert rows["Binance"]["fee_bps"] == 10.0
    assert rows["Bogus"]["fee_bps"] is None


# --------------------------------------------------------------------------- total_combos / total_strategies (honest denominators)


def test_total_counts_are_the_full_set_not_the_page(tmp_path, monkeypatch):
    """total_combos / total_strategies are computed over the WHOLE set, independent of the row `limit` — so the
    ribbon shows the honest denominator ('loaded of total') instead of passing off a page size as the universe."""
    store = _store(tmp_path)
    # Strategy A on two venues (2 combos), strategy B (1 combo), strategy C (1 combo) → 4 combos, 3 strategies.
    sid_a = store.insert("strategies", {"name": "A", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid_a = store.insert("strategy_versions", {"strategy_id": sid_a, "spec": {"name": "A"}, "generated_code": "", "code_hash": "h", "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z"})
    bt_a = store.insert("backtests", {"strategy_version_id": vid_a, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z"})
    for venue in ("binance", "kraken"):
        store.insert("backtest_symbols", {"backtest_id": bt_a, "strategy_version_id": vid_a, "symbol": "BTCUSDT", "venue_id": venue, "return_pct": "0.2", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 40, "verdict": "robust", "created_at": "2026-06-17T00:00:00Z"})
    _seed_cell(store, name="B", symbol="ETHUSDT", venue="binance", return_pct=0.10, verdict="robust")
    _seed_cell(store, name="C", symbol="SOLUSDT", venue="binance", return_pct=0.15, verdict="robust")
    # A tight limit truncates the rows, but the TRUE totals must NOT shrink with it.
    body = _client(monkeypatch, store).get("/lab/symbols?limit=1").json()
    assert len(body["rows"]) == 1                 # the page is capped…
    assert body["total_combos"] == 4              # …but the denominators count the whole set
    assert body["total_strategies"] == 3


def test_offset_pagination_reaches_every_combo_in_return_order(tmp_path, monkeypatch):
    """Server-side pagination: with a small `limit`, walking `offset` in steps covers EVERY combo exactly once, in
    the global return-desc order — so the /strategies page can page to the LAST combo, no row dropped or doubled."""
    store = _store(tmp_path)
    # 25 distinct combos with strictly-decreasing returns so the global order is unambiguous.
    n = 25
    for i in range(n):
        _seed_cell(store, name=f"S{i:02d}", symbol="BTCUSDT", venue="binance", return_pct=round(0.90 - i * 0.01, 4), verdict="robust")
    client = _client(monkeypatch, store)
    # Page through in windows of 10 (10 + 10 + 5) and stitch the combo ids together.
    seen: list[str] = []
    for off in (0, 10, 20):
        rows = client.get(f"/lab/symbols?limit=10&offset={off}").json()["rows"]
        seen.extend(f'{r["strategy_version_id"]}|{r["symbol"]}|{r["venue_id"]}' for r in rows)
    assert len(seen) == n            # every combo reached across the pages…
    assert len(set(seen)) == n       # …exactly once (no overlap between windows, no gap)
    # And the stitched order is strictly return-desc (0.90, 0.89, … 0.66) — the ranking survives pagination.
    returns: list[float] = []
    for off in (0, 10, 20):
        returns.extend(r["return_pct"] for r in client.get(f"/lab/symbols?limit=10&offset={off}").json()["rows"])
    assert returns == sorted(returns, reverse=True)
    # A deep offset past the end is an honest empty page, never an error or a wrap-around.
    assert client.get(f"/lab/symbols?limit=10&offset={n}").json()["rows"] == []


def test_offset_does_not_duplicate_the_first_page_track_only_rows(tmp_path, monkeypatch):
    """Track-only (cell-less) rows ride on page 0 ONLY — a later offset window must not re-emit them (they are not
    part of the ranked cell stream the offset indexes), so paging can't double a funded Paper bot."""
    store = _store(tmp_path)
    # Two cells + one track-only armed version. Page 0 (limit 2) fills with the two cells; the track-only row would
    # otherwise appear — but with a limit of 2 the reserve logic keeps it on page 0. Assert offset=2 (page 2) is empty
    # of that armed version (no cells left, and track-only never re-emitted off page 0).
    _seed_cell(store, name="CellA", symbol="BTCUSDT", venue="binance", return_pct=0.30, verdict="robust")
    _seed_cell(store, name="CellB", symbol="ETHUSDT", venue="binance", return_pct=0.20, verdict="robust")
    armed_vid = _seed_track_only_version(store, name="Diversified Time-Series Momentum", status="paper")
    client = _client(monkeypatch, store)
    page2 = client.get("/lab/symbols?limit=2&offset=2").json()["rows"]
    assert all(r["strategy_version_id"] != armed_vid for r in page2)  # not re-emitted on a later page


def test_thin_flag_tracks_the_real_gate_floor(tmp_path, monkeypatch):
    """A cell with FEWER trades than the gate's real min_trades is flagged `thin`; one at/above the floor is not.
    The threshold is the LIVE constant (settings.gates.min_trades), surfaced on the response — never hardcoded 30."""
    from cosmu.config.settings import GateSettings

    floor = GateSettings().min_trades  # the real gate floor (30 today) — the test reads it, never hardcodes it
    store = _store(tmp_path)
    _, thin_vid = _seed_cell(store, name="ThinCell", symbol="BTCUSDT", venue="binance", return_pct=0.20, verdict="robust", trades=floor - 1)
    _, fat_vid = _seed_cell(store, name="FatCell", symbol="ETHUSDT", venue="binance", return_pct=0.10, verdict="robust", trades=floor)
    body = _client(monkeypatch, store).get("/lab/symbols").json()
    assert body["min_trades"] == floor  # the live floor is surfaced so the web flags against it (no hardcode)
    rows = {r["strategy_version_id"]: r for r in body["rows"]}
    assert rows[thin_vid]["thin"] is True   # below the floor → flagged
    assert rows[fat_vid]["thin"] is False   # at the floor → not flagged
    assert rows[thin_vid]["trades"] == floor - 1 and rows[fat_vid]["trades"] == floor
