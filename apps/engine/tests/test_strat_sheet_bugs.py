# Two FRONT-DISPLAY bugs the operator caught on the Bots page + strategy sheet (2026-07-01). Neither moves money
# nor changes the Gate — they only fix what the front SHOWS.
#
#  BUG 1 — count mismatch. The sidebar "Bots" badge showed total_strategies (1,475 distinct algorithms) while the
#          table showed 1,000 combos of a 47,585 combo universe: three numbers under one "Bots" label. Root causes:
#          (a) apps/web/app/data/lab.ts SILENTLY DROPPED total_combos/total_strategies in its coalesce, so the page
#          fell back to loaded-slice counts; (b) the sidebar badge counted strategies, not combos. This module pins
#          the ENGINE side of (a): /lab/symbols returns the true whole-set denominators, independent of `limit`.
#  BUG 2 — paper equity sawtooth. The master loop writes a scope='track' snapshot from TWO writers each tick — the
#          paper clock (real fetched marks) AND the funder (a marks-dict carrying only freshly-funded cells, so an
#          already-held track re-marks to cost basis = starting_capital + 0 = the SEED). Interleaved, the stored
#          series sawtooths back to $1,000 with flat gaps. The read side now carries the last REAL mark forward over
#          those seed-collapse rows (honest_track_equity_series), so the sheet chart + the leaderboard equity read
#          the real marked book value, never the seed. The stored snapshots are untouched.

from __future__ import annotations

from cosmu.api._shared import honest_track_equity_series
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None, _env_file=None))


def _client(tmp_path, monkeypatch, name: str):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod
    store = _store(tmp_path, name)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app), store


# ── BUG 2 unit: the carry-forward transform ────────────────────────────────────────────────────────────────────


def _rows(*equities: str):
    # A minimal snapshot-row shape: honest_track_equity_series reads r["ts"] and r["equity"].
    return [{"ts": f"2026-06-{8 + i:02d}T00:00:00+00:00", "equity": e} for i, e in enumerate(equities)]


def test_honest_series_carries_last_real_mark_over_seed_collapse():
    # The real DAA pathology: a real mark ($1,024.75) interleaved with the funder's cost-basis collapse ($1,000).
    rows = _rows("1000.02", "1024.75", "1000.00", "1024.75", "1000.00", "1000.00")
    out = honest_track_equity_series(rows, "1000")
    vals = [v for _, v in out]
    # Not one snap-back to the $1,000 seed survives — every collapse row holds the last real mark ($1,024.75).
    assert vals == [1000.02, 1024.75, 1024.75, 1024.75, 1024.75, 1024.75]
    # The last honest value is the real marked book value, not the seed the last stored row happened to be.
    assert vals[-1] == 1024.75


def test_honest_series_flat_gap_holds_not_snaps_to_seed():
    # A RUN of funder-only ticks (no paper-clock price that window) = a flat gap; it must hold the last real mark,
    # never collapse to the seed (the "flat gap in the middle" the operator saw).
    rows = _rows("1019.29", "1000.00", "1000.00", "1000.00", "1000.00", "1024.75")
    vals = [v for _, v in honest_track_equity_series(rows, "1000")]
    assert vals == [1019.29, 1019.29, 1019.29, 1019.29, 1019.29, 1024.75]


def test_honest_series_keeps_leading_seed_before_any_real_mark():
    # Day-0 truth: before ANY real mark exists there is nothing to carry, so a leading seed row is kept as-is.
    rows = _rows("1000.00", "1000.00", "1010.00")
    vals = [v for _, v in honest_track_equity_series(rows, "1000")]
    assert vals == [1000.00, 1000.00, 1010.00]


def test_honest_series_entry_cost_basis_is_not_treated_as_a_collapse():
    # The entry-day cost-basis snapshot ($1,000.02) differs from the $1,000.00 seed — it is a REAL mark and is kept.
    rows = _rows("1000.02", "1000.00", "1005.00")
    vals = [v for _, v in honest_track_equity_series(rows, "1000")]
    assert vals == [1000.02, 1000.02, 1005.00]  # the .02 entry mark is the carry value over the .00 collapse


def test_honest_series_no_seed_is_a_passthrough():
    # Unknown starting_capital → nothing is a "collapse" → the series passes through untouched (never fabricates).
    rows = _rows("1000.00", "1010.00", "1000.00")
    vals = [v for _, v in honest_track_equity_series(rows, None)]
    assert vals == [1000.00, 1010.00, 1000.00]


# ── BUG 2 integration: the strategy sheet serves a smooth curve + honest headline value ─────────────────────────


def _seed_daa_like_track(store: Store) -> str:
    """A monthly buy-and-hold track: 6 legs bought once (a real paper fill), a starting_capital of $1,000, and a
    sawtooth snapshot series — the funder's $1,000 seed collapses interleaved with the paper clock's real marks."""
    sid = store.insert("strategies", {"name": "DAA-like", "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "DAA-like"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "paper", "kind": "quant", "created_at": utcnow(),
    })
    store.insert("tracks", {
        "strategy_version_id": vid, "symbol": None, "venue_id": None,
        "starting_capital": "1000", "equity": "1024.75", "return_pct": "2.48", "updated_at": utcnow(),
    })
    # A real paper fill so has_paper_fills is true (the sheet gates every money figure on this).
    run_id = store.insert("runs", {"mode": "sim", "seed": 1, "started_at": utcnow(), "status": "done"})
    store.insert("executions", {
        "run_id": run_id, "strategy_version_id": vid, "instrument_id": "SPY@ibkr", "venue_id": "ibkr", "side": "buy",
        "qty": "0.2", "price": "737.5", "fee": "0", "slippage": "0", "order_type": "market",
        "is_paper": 1, "ts": utcnow(), "fill_log": "{}",
    })
    # The sawtooth series: real marks interleaved with the funder's $1,000 seed collapse, ending on a seed row so
    # the OLD value_usd (snap_rows[-1]) would have shown the misleading $1,000.
    series = ["1000.02", "1020.08", "1000.00", "1024.75", "1000.00", "1024.75", "1000.00"]
    base = 8
    for i, eq in enumerate(series):
        store.insert("portfolio_snapshots", {
            "scope": "track", "ref_id": vid, "ts": f"2026-06-{base + i:02d}T00:00:00+00:00",
            "equity": eq, "cash": "0.00", "positions_value": eq, "pnl": "0.00", "drawdown": "0.0000",
        })
    return vid


def test_strategy_sheet_forward_equity_is_smooth_and_value_is_honest(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch, "sheet")
    vid = _seed_daa_like_track(store)
    data = client.get(f"/strategies/{vid}").json()
    curve = [p["value"] for p in data["forward_equity"]]
    # No point snaps back to the $1,000 seed — the sawtooth is gone.
    assert 1000.00 not in curve
    # The curve is the real marked trajectory: entry cost basis → held marks, ending at the true $1,024.75.
    assert curve == [1000.02, 1020.08, 1020.08, 1024.75, 1024.75, 1024.75, 1024.75]
    # The headline value reads the real marked book value, NOT the $1,000 seed the last stored row happened to be.
    assert data["value_usd"] == 1024.75
    assert data["starting_capital"] == 1000.0
    assert abs(data["pnl_usd"] - 24.75) < 1e-6  # a smooth ~+2.5%, matching the DB truth


# ── BUG 2 integration: the leaderboard equity picks the latest NON-seed snapshot ────────────────────────────────


def test_leaderboard_equity_prefers_latest_non_seed_snapshot(tmp_path, monkeypatch):
    """When the LAST stored track snapshot is the funder's $1,000 seed collapse, the leaderboard must read the
    latest REAL mark ($1,061.46), not flip the paper number to a flat 0%."""
    client, store = _client(tmp_path, monkeypatch, "lb")
    sid = store.insert("strategies", {"name": "seed-last", "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "seed-last"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "paper", "kind": "quant", "created_at": utcnow(),
    })
    store.insert("tracks", {
        "strategy_version_id": vid, "symbol": None, "venue_id": None,
        "starting_capital": "1000", "equity": "1061.46", "return_pct": "6.15", "updated_at": utcnow(),
    })
    run_id = store.insert("runs", {"mode": "sim", "seed": 1, "started_at": utcnow(), "status": "done"})
    store.insert("executions", {
        "run_id": run_id, "strategy_version_id": vid, "instrument_id": "SPY@ibkr", "venue_id": "ibkr", "side": "buy",
        "qty": "0.2", "price": "737.5", "fee": "0", "slippage": "0", "order_type": "market",
        "is_paper": 1, "ts": utcnow(), "fill_log": "{}",
    })
    # A series whose LATEST row (i=2) is the funder's $1,000 seed collapse; the real mark ($1,061.46) is earlier.
    for i, eq in enumerate(["1000.00", "1061.46", "1000.00"]):
        store.insert("portfolio_snapshots", {
            "scope": "track", "ref_id": vid, "ts": f"2026-06-{20 + i:02d}T00:00:00+00:00",
            "equity": eq, "cash": "0.00", "positions_value": eq, "pnl": "0.00", "drawdown": "0.0000",
        })
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    # paper_return_pct = (1061.46 / 1000 - 1) * 100 ≈ +6.15%, NOT the 0% a $1,000 seed-last read would give.
    assert row["paper_return_pct"] is not None
    assert abs(row["paper_return_pct"] - 6.146) < 0.01


# ── BUG 2 integration: the /overview hero curve + headline are seed-safe (the Paper page reader) ─────────────────


def test_overview_hero_curve_and_headline_are_seed_safe(tmp_path, monkeypatch):
    """The Paper hero reads /overview's aggregate curve. On a FUNDER tick the aggregate `pnl` collapses to ~0 so
    value = allocated + 0 = the allocated seed baseline; interleaved with real marks the raw series sawtooths AND
    the raw last snapshot mis-reads the headline. /overview must carry the last real mark (honest_track_equity_series,
    seed = allocated) for BOTH the curve and pnl_net — it was the third reader missing the fix the sheet + LB have."""
    client, store = _client(tmp_path, monkeypatch, "overview")
    sid = store.insert("strategies", {"name": "agg", "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "agg"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "paper", "kind": "quant", "created_at": utcnow(),
    })
    # allocated = Σ starting_capital of forward-stage tracks = $10,000 (the seed baseline the funder collapses to).
    store.insert("tracks", {
        "strategy_version_id": vid, "symbol": None, "venue_id": None,
        "starting_capital": "10000", "equity": "10024.75", "return_pct": "0.2475", "updated_at": utcnow(),
    })
    # Aggregate pnl sawtooth: real marks (0.02, 20.08, 24.75) interleaved with the funder's pnl=0 collapse, ENDING
    # on a collapse so the raw last snapshot (pnl 0) would mis-read the headline as $0 P&L.
    for i, pnl in enumerate(["0.02", "20.08", "0.00", "24.75", "0.00", "24.75", "0.00"]):
        eq = 10000.0 + float(pnl)
        store.insert("portfolio_snapshots", {
            "scope": "aggregate", "ref_id": "global", "ts": f"2026-06-{8 + i:02d}T00:00:00+00:00",
            "equity": f"{eq:.2f}", "cash": "0.00", "positions_value": f"{eq:.2f}", "pnl": pnl, "drawdown": "0.0000",
        })
    data = client.get("/overview").json()
    curve = [round(p["value"], 2) for p in data["equity_curve"]]
    # No point snaps back to the $10,000 allocated floor after a real mark — the sawtooth is gone.
    assert curve == [10000.02, 10020.08, 10020.08, 10024.75, 10024.75, 10024.75, 10024.75]
    assert 10000.00 not in curve
    # The headline reads the last REAL mark's P&L (+$24.75), not the $0 the funder-collapse last row stored.
    assert round(data["pnl_net"], 2) == 24.75


# ── BUG 1: the engine serves the TRUE whole-set denominators, independent of the row limit ──────────────────────


def _combo(store: Store, *, name: str, symbol: str, venue: str) -> None:
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": utcnow(),
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.05", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 80, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow(),
    })
    store.insert("backtest_symbols", {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": "0.10", "sharpe": "1.2", "max_drawdown": "0.08", "trades": 80, "verdict": "robust",
        "oos_window_days": 365.0, "created_at": utcnow(),
    })


def test_lab_symbols_totals_are_the_whole_set_not_the_limited_slice(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch, "lab")
    # 3 strategies × 2 symbols = 6 combos across 3 distinct algorithms.
    for name in ("A", "B", "C"):
        _combo(store, name=name, symbol="BTCUSDT", venue="binance")
        _combo(store, name=name, symbol="ETHUSDT", venue="binance")
    # limit=2 caps the loaded rows to 2, but the TRUE denominators must still reflect all 6 combos / 6 algos.
    data = client.get("/lab/symbols?limit=2").json()
    assert len(data["rows"]) == 2                 # the response IS capped …
    assert data["total_combos"] == 6              # … but the combo denominator is the whole set (no silent cap)
    assert data["total_strategies"] == 6          # 6 distinct strategy_ids (each _combo makes a fresh strategy)
