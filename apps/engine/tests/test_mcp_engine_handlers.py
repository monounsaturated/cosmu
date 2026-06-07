"""Offline, deterministic test of the READ-ONLY engine/Gate MCP handlers (mcp/engine/handlers.py).

Every handler is exercised against a tmp SQLite Store with NO network and NO live engine — the autouse
network guard in conftest fails any test that opens a real socket, so this proves the surface is genuinely
offline-driveable. The contract under test: each handler reads honestly, and the propose-only Gate evaluation
returns a real PASS/STOP verdict while moving no money (no track funded, no order armed, no live toggle).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store

# Load mcp/engine/handlers.py directly (mcp/engine is not an importable package; it's launched as a script).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HANDLERS_PATH = _REPO_ROOT / "mcp" / "engine" / "handlers.py"
_spec = importlib.util.spec_from_file_location("cosmu_mcp_engine_handlers", _HANDLERS_PATH)
handlers = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = handlers
_spec.loader.exec_module(handlers)


def _store(tmp_path, name="mcp") -> Store:
    # no openrouter_api_key → fully offline (the LLM is ingest-only and never touched by these read handlers).
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_strategy(store: Store, *, sid: str, name: str, status: str, dsharpe: str = "1.5") -> str:
    """Insert one strategy + one version (+ optional backtest) using the engine's own Store writer."""
    now = "2026-06-07T00:00:00Z"
    store.insert("strategies", {"id": sid, "name": name, "thesis": f"thesis-{sid}", "origin": "test", "created_at": now})
    vid = f"{sid}-v1"
    store.insert(
        "strategy_versions",
        {
            "id": vid, "strategy_id": sid, "spec": "{}", "generated_code": "", "code_hash": "h",
            "params": "{}", "origin": "test", "status": status, "created_at": now,
        },
    )
    store.insert(
        "backtests",
        {
            "id": f"{vid}-bt", "strategy_version_id": vid, "kind": "wfo", "oos_return": "0.12",
            "sharpe": "1.0", "sortino": "0", "deflated_sharpe": dsharpe, "max_dd": "0.1", "win_rate": "0.55",
            "num_trades": 42, "pbo": "0.2", "trials_counted": 10, "folds_positive": 3,
            "passed_gates": 1, "holdout_passed": 1, "created_at": now,
        },
    )
    return vid


# --- DB read handlers -------------------------------------------------------------------------


def test_list_strategies_reads_latest_version_and_filters_by_status(tmp_path):
    store = _store(tmp_path)
    _seed_strategy(store, sid="s1", name="Alpha", status="funded")
    _seed_strategy(store, sid="s2", name="Beta", status="killed")

    all_rows = handlers.list_strategies(store)
    assert {r["name"] for r in all_rows} == {"Alpha", "Beta"}
    assert all(set(r) >= {"id", "name", "thesis", "status", "origin", "created_at"} for r in all_rows)

    funded = handlers.list_strategies(store, status="funded")
    assert [r["name"] for r in funded] == ["Alpha"]
    assert funded[0]["status"] == "funded"


def test_list_strategies_limit_is_bounded_and_empty_store_is_empty(tmp_path):
    store = _store(tmp_path, "empty")
    assert handlers.list_strategies(store) == []
    # limit is clamped to >=1 even if a caller passes 0/negative — never an invalid SQL LIMIT.
    _seed_strategy(store, sid="s1", name="Alpha", status="active")
    assert len(handlers.list_strategies(store, limit=0)) == 1


def test_list_tracks_reads_marked_state(tmp_path):
    store = _store(tmp_path)
    vid = _seed_strategy(store, sid="s1", name="Alpha", status="funded")
    store.insert(
        "tracks",
        {"id": "t1", "strategy_version_id": vid, "starting_capital": "100000", "equity": "101000",
         "return_pct": "1.0", "updated_at": "2026-06-07T01:00:00Z"},
    )
    tracks = handlers.list_tracks(store)
    assert len(tracks) == 1
    t = tracks[0]
    assert t["name"] == "Alpha"
    assert t["equity"] == pytest.approx(101000.0)
    assert t["return_pct"] == pytest.approx(1.0)
    assert isinstance(t["equity"], float)  # Decimal coerced to JSON-able float


def _add_verdict(store: Store, ts: str, decision: str, data_source: str, payload: str) -> None:
    # gate_verdicts.id is INTEGER AUTOINCREMENT, so go through the raw writer (Store.insert would inject a
    # string UUID id and trip the PK datatype check). Lets the AUTOINCREMENT assign the id.
    with store.batch() as w:
        w.execute(
            "INSERT INTO gate_verdicts (ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
            (ts, decision, data_source, payload),
        )


def test_read_gate_verdicts_returns_newest_first(tmp_path):
    store = _store(tmp_path)
    _add_verdict(store, "2026-06-01T00:00:00Z", "STOP", "synthetic", "{}")
    _add_verdict(store, "2026-06-05T00:00:00Z", "PASS", "live", '{"k":1}')
    verdicts = handlers.read_gate_verdicts(store, limit=10)
    assert [v["decision"] for v in verdicts] == ["PASS", "STOP"]  # newest first
    assert verdicts[0]["data_source"] == "live"


def test_read_leaderboard_ranks_by_deflated_sharpe(tmp_path):
    store = _store(tmp_path)
    _seed_strategy(store, sid="lo", name="Low", status="active", dsharpe="0.3")
    _seed_strategy(store, sid="hi", name="High", status="funded", dsharpe="2.7")
    board = handlers.read_leaderboard(store)
    assert [r["name"] for r in board] == ["High", "Low"]  # highest deflated Sharpe first
    assert board[0]["deflated_sharpe"] == pytest.approx(2.7)
    assert board[0]["num_trades"] == 42


def test_read_overview_aggregates_curve_costs_and_live_flag(tmp_path):
    store = _store(tmp_path)
    snap = {"scope": "aggregate", "ref_id": "aggregate", "cash": "0", "positions_value": "0", "drawdown": "0"}
    store.insert("portfolio_snapshots", {"id": "p1", "ts": "2026-06-01T00:00:00Z", "equity": "100000", "pnl": "0", **snap})
    store.insert("portfolio_snapshots", {"id": "p2", "ts": "2026-06-05T00:00:00Z", "equity": "100500", "pnl": "500", **snap})
    store.insert("costs", {"id": "c1", "ts": "2026-06-01T00:00:00Z", "category": "data", "vendor": "x", "amount": "12.5", "currency": "USD", "meta": "{}"})
    ov = handlers.read_overview(store)
    assert len(ov["equity_curve"]) == 2
    assert ov["equity_curve"][0]["ts"] < ov["equity_curve"][1]["ts"]  # ascending
    assert ov["pnl_net"] == pytest.approx(500.0)
    assert ov["costs"] == [{"category": "data", "amount": pytest.approx(12.5)}]
    assert ov["live_enabled"] is False  # migrate() seeds the global toggle to 0; nothing here flips it


# --- Propose-only Gate evaluation -------------------------------------------------------------


def test_evaluate_signal_gate_emits_a_verdict_without_moving_money(tmp_path):
    """The Gate evaluation returns a real PASS/STOP verdict and records counted trials (honest accounting),
    but it must NEVER fund a track, arm an order, or toggle live. Run on the null fixture (edge=False) the
    honest Gate STOPs."""
    store = _store(tmp_path, "gate")
    verdict = handlers.evaluate_signal_gate(store, edge=False, seed=7, n=400)

    assert verdict["decision"] in {"PASS", "STOP"}
    assert verdict["decision"] == "STOP"  # null inputs → an honest Gate must STOP
    assert verdict["reasons"], "a STOP verdict must name why it stopped"
    assert set(verdict) >= {"decision", "passed", "deflated_sharpe_prob", "cscv_pbo", "attempts"}

    # PROPOSE-ONLY invariant: the Gate emits a verdict + counts trials, but moves no money. No track was funded,
    # no order armed, no live toggle flipped. (gate_verdicts is written by the loop's persistence layer, not by
    # evaluate_gate itself — so even the verdict ledger stays empty here.)
    assert store.rows("SELECT 1 FROM tracks") == []
    assert store.rows("SELECT 1 FROM portfolio_snapshots") == []
    live = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    assert live is not None and not live["enabled"]
    # the gate DID do honest multiple-testing accounting (counted attempts in the trial ledger).
    assert len(store.rows("SELECT 1 FROM trials")) == verdict["attempts"] > 0


def test_evaluate_signal_gate_is_deterministic(tmp_path):
    a = handlers.evaluate_signal_gate(_store(tmp_path, "a"), edge=True, seed=7, n=400)
    b = handlers.evaluate_signal_gate(_store(tmp_path, "b"), edge=True, seed=7, n=400)
    assert (a["decision"], a["deflated_sharpe_prob"], a["cscv_pbo"], a["best_return"]) == (
        b["decision"], b["deflated_sharpe_prob"], b["cscv_pbo"], b["best_return"],
    )
