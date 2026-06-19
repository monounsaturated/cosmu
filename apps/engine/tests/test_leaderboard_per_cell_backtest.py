# Fix 3 — the /leaderboard money surface must show the per-cell ANNUALIZED backtest return for each track's OWN
# (symbol, venue), NOT the pooled non-annualized version-level oos_return. backtest_return_pct_annualized re-keys the
# BACKTEST column to the exact triplet the track forward-tests, annualized over that cell's OWN OOS window. The
# forward paper_return_pct (the real marked money) is unchanged — this only fixes the BACKTEST column shown alongside.
# Honest NULL when no matching cell exists (documented arm / legacy version-wide track); never the pooled fallback.

from __future__ import annotations

import math

import cosmu.api.app as app_mod
from cosmu.api._shared import annualized_return
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/lbcell.sqlite3", openrouter_api_key=None, _env_file=None)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app), store


def _version_with_pooled_backtest(store: Store, *, name: str, pooled_oos: str = "0.05") -> str:
    """A version + its pooled, version-level backtest (oos_return = the OLD leaderboard headline). The per-cell
    return is DELIBERATELY different so the test proves the new column reads the CELL, not this pooled number."""
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": utcnow()})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "paper", "kind": "quant", "created_at": utcnow(),
    })
    store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": pooled_oos, "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 80, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 1,
        "oos_start": "2024-01", "oos_end": "2025-12", "created_at": utcnow(),
    })
    return vid


def _cell(store: Store, vid: str, *, symbol: str, venue: str, return_pct: str, window_days: float = 365.0) -> None:
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.0", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 80, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow(),
    })
    store.insert("backtest_symbols", {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": return_pct, "sharpe": "1.2", "max_drawdown": "0.08", "trades": 80, "verdict": "robust",
        "oos_window_days": window_days, "created_at": utcnow(),
    })


def _track(store: Store, vid: str, *, symbol: str, venue: str) -> None:
    store.insert("tracks", {
        "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "starting_capital": "1000", "equity": "1000.00", "return_pct": "0.00", "updated_at": utcnow(),
    })


def test_backtest_column_is_the_tracks_own_cell_annualized_not_the_pooled(tmp_path, monkeypatch):
    """The track trades BTCUSDT@binance; its cell returned +30% over a 365d window. The new BACKTEST column reads
    THAT cell annualized (+30%/yr), NOT the pooled version-level +5% the old leaderboard headlined."""
    client, store = _client(tmp_path, monkeypatch)
    vid = _version_with_pooled_backtest(store, name="Per-cell momentum", pooled_oos="0.05")
    _cell(store, vid, symbol="BTCUSDT", venue="binance", return_pct="0.30", window_days=365.0)
    _cell(store, vid, symbol="ETHUSDT", venue="binance", return_pct="0.99", window_days=365.0)  # a SIBLING — must be ignored
    _track(store, vid, symbol="BTCUSDT", venue="binance")
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["backtest_return_pct_annualized"] is not None
    # +30% over ~1y annualizes to ~+30%/yr — the track's OWN cell, never the +5% pooled or the +99% sibling.
    assert math.isclose(row["backtest_return_pct_annualized"], annualized_return(0.30, 365.0), rel_tol=1e-6)
    # The OLD pooled headline is still surfaced separately (back-compat) and is DISTINCT from the per-cell number.
    assert math.isclose(row["track_return_pct"], 5.0, abs_tol=1e-6)  # pooled 0.05 * 100
    assert row["backtest_return_pct_annualized"] != row["track_return_pct"]


def test_backtest_column_null_when_no_matching_cell(tmp_path, monkeypatch):
    """A track whose (symbol, venue) has NO backtest_symbols cell (documented arm) → honest NULL, never the pooled
    fallback. The pooled track_return_pct still shows, so the row isn't blank — but the per-cell column is "—"."""
    client, store = _client(tmp_path, monkeypatch)
    vid = _version_with_pooled_backtest(store, name="Armed-no-cell", pooled_oos="0.07")
    _track(store, vid, symbol="SOLUSDT", venue="hyperliquid")  # no cell for this triplet
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["backtest_return_pct_annualized"] is None  # honest "—", never the +7% pooled
    assert math.isclose(row["track_return_pct"], 7.0, abs_tol=1e-6)  # pooled still surfaced


def test_per_cell_backtest_does_not_disturb_the_forward_paper_number(tmp_path, monkeypatch):
    """The forward paper_return_pct (the REAL marked money) is untouched by the re-key — it stays null at day-0
    even when the per-cell BACKTEST column is populated. The two are independent surfaces."""
    client, store = _client(tmp_path, monkeypatch)
    vid = _version_with_pooled_backtest(store, name="Forward-untouched", pooled_oos="0.05")
    _cell(store, vid, symbol="BTCUSDT", venue="binance", return_pct="0.20", window_days=365.0)
    _track(store, vid, symbol="BTCUSDT", venue="binance")  # opened, never marked / no paper fill
    row = next(r for r in client.get("/leaderboard").json()["rows"] if r["version_id"] == vid)
    assert row["backtest_return_pct_annualized"] is not None  # BACKTEST column populated from the cell
    assert row["paper_return_pct"] is None                    # FORWARD money still honest day-0 null
