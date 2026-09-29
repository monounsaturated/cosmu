# GENEROUS PAPER for near-miss cells (operator-approved 2026-06-18). The brut gate stays STRICT (DSR>=0.95 — the
# gate VERDICT is never loosened here). But a cell that FAILS the gate yet is genuinely promising — sharpe>1.0 AND
# trades>=30 AND return>0 (net of fees) — is routed to a GENEROUS PAPER (watch) lane INSTEAD of being killed:
# tagged backtest_symbols.verdict='watch', funded on the SAME zero-real-capital, born-honest paper track survivors
# use, and forward-tested. The forward/paper performance then separates real from lucky; the human still arms live
# only on what proves out. These tests pin: (1) the near-miss predicate; (2) the finder/loop watch routing (verdict
# + paper track + lane='watch' event + version status='paper'); (3) a gate-pass cell still papers normally; (4) a
# thin/negative cell gets NO watch track; (5) the gate verdict (passed_gates / per-cell 'pass') is unchanged; and
# (6) the funder funds a watch cell so the paper clock (and drift defund) reaches it.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store
from cosmu.lab.finder import CellResult, StrategyFinder, VariantResult
from cosmu.master.live_eligibility import cell_id
from cosmu.master.scorer import BacktestMetrics
from cosmu.master.tracks import (
    NEAR_MISS_MIN_SHARPE,
    NEAR_MISS_MIN_TRADES,
    WATCH_VERDICT,
    is_near_miss_cell,
    open_paper_track,
)
from cosmu.orchestrator.loop import _survivor_tracks
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec


def _store(tmp_path, name="genpaper") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _finder(tmp_path) -> StrategyFinder:
    store = _store(tmp_path)
    return StrategyFinder(settings=store.settings, store=store, market_data=None)


# ──────────────────────────────────────────────────────────── the predicate (unit) ──

def test_near_miss_predicate_matches_operator_criterion():
    # The DeFi-flow-on-SOL exemplar the operator named: sharpe 1.37 / 114 trades / +6.1% → near-miss.
    assert is_near_miss_cell(sharpe=1.37, trades=114, return_pct=0.061) is True


def test_near_miss_predicate_rejects_each_failing_leg():
    # Sharpe at/under the floor (strictly greater than 1.0 required).
    assert is_near_miss_cell(sharpe=NEAR_MISS_MIN_SHARPE, trades=50, return_pct=0.05) is False
    assert is_near_miss_cell(sharpe=0.9, trades=50, return_pct=0.05) is False
    # Too few of its OWN trades to judge.
    assert is_near_miss_cell(sharpe=1.5, trades=NEAR_MISS_MIN_TRADES - 1, return_pct=0.05) is False
    # Did not make money (net of fees).
    assert is_near_miss_cell(sharpe=1.5, trades=50, return_pct=0.0) is False
    assert is_near_miss_cell(sharpe=1.5, trades=50, return_pct=-0.01) is False
    # The exact lower boundary that DOES qualify.
    assert is_near_miss_cell(sharpe=1.01, trades=NEAR_MISS_MIN_TRADES, return_pct=0.0001) is True


# ──────────────────────────────────────────── finder _persist: three cell dispositions ──

def _cell(symbol, *, passed, holdout_passed=False, sharpe="1.0", num_trades=40, oos="0.05", dsr=0.5, reasons=None):
    metrics = BacktestMetrics(
        oos_return=Decimal(oos), sharpe=Decimal(sharpe), sortino=Decimal("1.5"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.6"), num_trades=num_trades,
        regime_returns={"bull": 0.05},
    )
    return CellResult(
        symbol=symbol, venue_id="binance", metrics=metrics, deflated_sharpe=dsr,
        trades=num_trades, passed=passed, holdout_passed=holdout_passed, reasons=reasons or [],
    )


def _variant(*, code_hash, gate_passed, cells, per_symbol, reasons=None):
    any_cell = next(iter(cells.values()))
    return VariantResult(
        config_tag="cfg", code_hash=code_hash, metrics=any_cell.metrics,
        deflated_sharpe=any_cell.deflated_sharpe, profit_factor=1.5, net_profit=0.04,
        gate_passed=gate_passed, reasons=reasons or [], fitted_params={}, promoted=gate_passed,
        holdout_passed=gate_passed, per_symbol=per_symbol, cells=cells,
    )


def _persist_one(finder, *, gate_passed, cells, per_symbol, reasons=None):
    spec = seed_orb_fvg_spec()
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    variant = _variant(code_hash=compiled.code_hash, gate_passed=gate_passed, cells=cells,
                        per_symbol=per_symbol, reasons=reasons)
    variant.fitted_params = fitted
    venue = default_catalog().venue_for(spec.universe.venues)
    finder._persist(spec, [variant], {}, venue)
    return variant.version_id


def test_near_miss_failed_cell_gets_watch_verdict_and_paper_track(tmp_path):
    """A gate-FAILED near-miss cell (sharpe>1 / trades>=30 / return>0) is tagged 'watch', funds a born-honest paper
    track, emits a lane='watch' track_opened, and its version goes to PAPER (so the funder + executor reach it) —
    but it is NEVER a gate pass (no 'pass' verdict, no finder_survivor event, passed_gates=0)."""
    finder = _finder(tmp_path)
    cells = {"SOLUSDT": _cell("SOLUSDT", passed=False, sharpe="1.37", num_trades=114, oos="0.061",
                              reasons=["deflated_sharpe"])}
    per_symbol = {"SOLUSDT": {"return": 0.061, "sharpe": 1.37, "max_drawdown": 0.12, "trades": 114.0}}
    vid = _persist_one(finder, gate_passed=False, cells=cells, per_symbol=per_symbol, reasons=["deflated_sharpe"])
    assert vid is not None

    # (a) per-cell row tagged 'watch' (not its kill reason, not 'pass').
    bs = finder.store.row(
        "SELECT verdict FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'SOLUSDT'", (vid,))
    assert bs["verdict"] == WATCH_VERDICT

    # (b) a born-honest paper track exists for the watch cell (equity == starting_capital, return_pct seeded 0).
    tr = finder.store.row(
        "SELECT symbol, venue_id, return_pct, equity, starting_capital FROM tracks WHERE strategy_version_id = ?",
        (vid,))
    assert tr["symbol"] == "SOLUSDT" and tr["venue_id"] == "binance"
    assert float(tr["return_pct"]) == 0.0
    assert float(tr["equity"]) == float(tr["starting_capital"])

    # (c) the track_opened event is tagged lane='watch' (distinct from a gate-pass paper).
    cid = cell_id(vid, "SOLUSDT", "binance")
    ev = finder.store.row(
        "SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ?", (cid,))
    assert ev is not None and '"lane": "watch"' in ev["payload"]

    # (d) NOT a gate pass: no finder_survivor event; the backtest still records the gate fail.
    surv = finder.store.row(
        "SELECT COUNT(*) AS n FROM events WHERE kind = 'finder_survivor' AND ref_id = ?", (cid,))
    assert surv["n"] == 0
    bt = finder.store.row(
        "SELECT passed_gates FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'", (vid,))
    assert int(bt["passed_gates"]) == 0

    # (e) the version is ALIVE on the paper lane (so the clock/funder step it), not killed.
    sv = finder.store.row("SELECT status, kill_reason FROM strategy_versions WHERE id = ?", (vid,))
    assert sv["status"] == "paper"
    assert sv["kill_reason"] is None


def test_gate_pass_cell_still_papers_normally_not_watch(tmp_path):
    """A gate-PASS cell keeps verdict='pass' (never re-tagged 'watch'), emits a finder_survivor event, and its
    version stays 'screened' — the generous-paper lane is additive, it never touches the survivor path."""
    finder = _finder(tmp_path)
    cells = {"BTCUSDT": _cell("BTCUSDT", passed=True, holdout_passed=True, sharpe="1.5", num_trades=40,
                              oos="0.05", dsr=0.96)}
    per_symbol = {"BTCUSDT": {"return": 0.05, "sharpe": 1.5, "max_drawdown": 0.10, "trades": 40.0}}
    vid = _persist_one(finder, gate_passed=True, cells=cells, per_symbol=per_symbol)

    bs = finder.store.row(
        "SELECT verdict FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", (vid,))
    assert bs["verdict"] == "pass"
    cid = cell_id(vid, "BTCUSDT", "binance")
    surv = finder.store.row(
        "SELECT COUNT(*) AS n FROM events WHERE kind = 'finder_survivor' AND ref_id = ?", (cid,))
    assert surv["n"] == 1
    ev = finder.store.row("SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ?", (cid,))
    assert ev is not None and '"lane": "finder"' in ev["payload"]
    sv = finder.store.row("SELECT status FROM strategy_versions WHERE id = ?", (vid,))
    assert sv["status"] == "screened"


def test_thin_or_negative_cell_gets_no_watch_track(tmp_path):
    """A gate-FAILED cell that is NOT a near-miss (too few trades, OR net-negative, OR low sharpe) keeps its kill
    reason, opens NO track, and its version is KILLED — the generous lane only catches the genuinely promising."""
    finder = _finder(tmp_path)
    cells = {
        "ETHUSDT": _cell("ETHUSDT", passed=False, sharpe="1.5", num_trades=10, oos="0.05",
                         reasons=["min_trades_per_symbol"]),   # too thin
        "XRPUSDT": _cell("XRPUSDT", passed=False, sharpe="1.5", num_trades=50, oos="-0.02",
                         reasons=["buy_and_hold"]),            # net-negative
        "ADAUSDT": _cell("ADAUSDT", passed=False, sharpe="0.5", num_trades=50, oos="0.05",
                         reasons=["deflated_sharpe"]),         # weak sharpe
    }
    per_symbol = {
        "ETHUSDT": {"return": 0.05, "sharpe": 1.5, "max_drawdown": 0.1, "trades": 10.0},
        "XRPUSDT": {"return": -0.02, "sharpe": 1.5, "max_drawdown": 0.1, "trades": 50.0},
        "ADAUSDT": {"return": 0.05, "sharpe": 0.5, "max_drawdown": 0.1, "trades": 50.0},
    }
    vid = _persist_one(finder, gate_passed=False, cells=cells, per_symbol=per_symbol,
                       reasons=["min_trades_per_symbol"])

    verdicts = {
        r["symbol"]: r["verdict"]
        for r in finder.store.rows(
            "SELECT symbol, verdict FROM backtest_symbols WHERE strategy_version_id = ?", (vid,))
    }
    assert WATCH_VERDICT not in verdicts.values()  # none promoted to watch
    assert verdicts["ETHUSDT"] == "min_trades_per_symbol"
    n_tracks = finder.store.row("SELECT COUNT(*) AS n FROM tracks WHERE strategy_version_id = ?", (vid,))["n"]
    assert n_tracks == 0  # no track opened for any non-near-miss cell
    sv = finder.store.row("SELECT status, kill_reason FROM strategy_versions WHERE id = ?", (vid,))
    assert sv["status"] == "killed"
    assert sv["kill_reason"]  # truly killed → a recorded reason


def test_mixed_version_passes_one_cell_and_watches_another(tmp_path):
    """One cell passes the gate (→ 'pass', survivor), a sibling near-miss is watched (→ 'watch') — both fund a paper
    track on their OWN symbol. The gate verdict is per cell and unchanged; the watch cell never becomes a survivor."""
    finder = _finder(tmp_path)
    cells = {
        "BTCUSDT": _cell("BTCUSDT", passed=True, holdout_passed=True, sharpe="1.6", num_trades=45,
                         oos="0.07", dsr=0.97),
        "SOLUSDT": _cell("SOLUSDT", passed=False, sharpe="1.3", num_trades=114, oos="0.061",
                         reasons=["deflated_sharpe"]),
    }
    per_symbol = {
        "BTCUSDT": {"return": 0.07, "sharpe": 1.6, "max_drawdown": 0.1, "trades": 45.0},
        "SOLUSDT": {"return": 0.061, "sharpe": 1.3, "max_drawdown": 0.12, "trades": 114.0},
    }
    vid = _persist_one(finder, gate_passed=True, cells=cells, per_symbol=per_symbol)

    verdicts = {
        r["symbol"]: r["verdict"]
        for r in finder.store.rows(
            "SELECT symbol, verdict FROM backtest_symbols WHERE strategy_version_id = ?", (vid,))
    }
    assert verdicts["BTCUSDT"] == "pass"
    assert verdicts["SOLUSDT"] == WATCH_VERDICT
    # The gate-pass cell is a survivor; the watch cell is not.
    assert finder.store.row(
        "SELECT COUNT(*) AS n FROM events WHERE kind='finder_survivor' AND ref_id=?",
        (cell_id(vid, "BTCUSDT", "binance"),))["n"] == 1
    assert finder.store.row(
        "SELECT COUNT(*) AS n FROM events WHERE kind='finder_survivor' AND ref_id=?",
        (cell_id(vid, "SOLUSDT", "binance"),))["n"] == 0


# ──────────────────────────────────────────────────── the funder reaches a watch cell ──

def _seed_watch_version(store: Store, *, symbol="SOLUSDT") -> str:
    """A gate-FAILED version (passed_gates=0, status='paper') carrying a single 'watch' cell + its born-honest
    paper track — exactly what the finder/loop persists for a near-miss. Returns the version_id."""
    with store.batch() as b:
        sid = b.insert("strategies", {"name": "DeFi flow", "thesis": "t", "origin": "finder",
                                      "created_at": "2026-06-18T00:00:00Z"})
        vid = b.insert("strategy_versions", {
            "strategy_id": sid,
            "spec": {"name": "DeFi flow", "universe": {"asset_classes": ["crypto"], "venues": ["binance"]}},
            "generated_code": "", "code_hash": "wh", "params": {}, "origin": "finder", "status": "paper",
            "created_at": "2026-06-18T00:00:00Z",
        })
        bt = b.insert("backtests", {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.061", "sharpe": "1.37",
            "sortino": "1.5", "deflated_sharpe": "0.85", "max_dd": "0.12", "win_rate": "0.55", "num_trades": 114,
            "pbo": "0.3", "trials_counted": 1, "folds_positive": 4, "passed_gates": 0, "holdout_passed": 0,
            "created_at": "2026-06-18T00:00:00Z",
        })
        b.insert("backtest_symbols", {
            "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": "binance",
            "return_pct": "0.061", "sharpe": "1.37", "max_drawdown": "0.12", "trades": 114,
            "verdict": WATCH_VERDICT, "created_at": "2026-06-18T00:00:00Z",
        })
        open_paper_track(b, version_id=vid, starting_capital=Decimal("1000"), symbol=symbol, venue_id="binance")
    return vid


def test_funder_funds_a_watch_cell(tmp_path):
    """The funder fans out the SAME standalone paper track for a 'watch' cell as for a 'pass' cell — so the paper
    clock (and the anticipatory drift defund) reaches a watch cell, separating real from lucky going forward. A
    watch version has passed_gates=0; the funder must NOT require the version-level gate flags for a watch cell."""
    store = _store(tmp_path, name="fundwatch")
    vid = _seed_watch_version(store, symbol="SOLUSDT")
    triples = _survivor_tracks(store, default_catalog())
    funded = [(sym, vn) for (v, _t, sym, vn) in triples if v == vid]
    assert funded == [("SOLUSDT", "binance")], f"funder must fund the watch cell, got {funded}"


def test_funder_still_skips_a_plain_failed_cell(tmp_path):
    """A genuinely-failed cell (verdict != 'pass'/'watch') is NEVER funded — the generous lane only widens to watch,
    it does not fund every reject."""
    store = _store(tmp_path, name="fundfail")
    with store.batch() as b:
        sid = b.insert("strategies", {"name": "Dud", "thesis": "t", "origin": "finder",
                                      "created_at": "2026-06-18T00:00:00Z"})
        vid = b.insert("strategy_versions", {
            "strategy_id": sid,
            "spec": {"name": "Dud", "universe": {"asset_classes": ["crypto"], "venues": ["binance"]}},
            "generated_code": "", "code_hash": "dud", "params": {}, "origin": "finder", "status": "killed",
            "created_at": "2026-06-18T00:00:00Z",
        })
        bt = b.insert("backtests", {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "-0.02", "sharpe": "0.3",
            "sortino": "0.3", "deflated_sharpe": "0.4", "max_dd": "0.2", "win_rate": "0.4", "num_trades": 50,
            "pbo": "0.6", "trials_counted": 1, "folds_positive": 2, "passed_gates": 0, "holdout_passed": 0,
            "created_at": "2026-06-18T00:00:00Z",
        })
        b.insert("backtest_symbols", {
            "backtest_id": bt, "strategy_version_id": vid, "symbol": "XRPUSDT", "venue_id": "binance",
            "return_pct": "-0.02", "sharpe": "0.3", "max_drawdown": "0.2", "trades": 50,
            "verdict": "deflated_sharpe", "created_at": "2026-06-18T00:00:00Z",
        })
    triples = _survivor_tracks(store, default_catalog())
    assert not [t for t in triples if t[0] == vid]


# ────────────────────────────────────── the autonomous loop (FarmLoop) watch routing ──

def test_evolution_loop_routes_near_miss_to_watch(tmp_path):
    """The autonomous loop's _persist mirrors the finder sweep: a gate-FAILED near-miss cell is tagged 'watch',
    funds a born-honest paper track + a lane='watch' track_opened, and its version goes to PAPER (never KILLED) —
    while a sibling true-fail cell keeps its kill reason and opens no track."""
    from cosmu.evolution.loop import Candidate, FarmLoop, _BrutCell, _Screened
    from cosmu.ml.survival import load_survival_model

    store = _store(tmp_path, name="loopwatch")
    loop = FarmLoop(settings=store.settings, store=store, market_data=None)
    spec = seed_orb_fvg_spec()
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    survival = load_survival_model(store)

    near = _BrutCell(
        symbol="SOLUSDT", venue_id="binance",
        metrics=BacktestMetrics(oos_return=Decimal("0.061"), sharpe=Decimal("1.37"), sortino=Decimal("1.5"),
                                max_drawdown=Decimal("0.12"), win_rate=Decimal("0.55"), num_trades=114,
                                regime_returns={"bull": 0.061}),
        deflated_sharpe=0.85, trades=114, passed=False, reasons=["deflated_sharpe"],
    )
    dud = _BrutCell(
        symbol="XRPUSDT", venue_id="binance",
        metrics=BacktestMetrics(oos_return=Decimal("-0.02"), sharpe=Decimal("0.3"), sortino=Decimal("0.3"),
                                max_drawdown=Decimal("0.2"), win_rate=Decimal("0.4"), num_trades=50,
                                regime_returns={"bull": -0.02}),
        deflated_sharpe=0.4, trades=50, passed=False, reasons=["deflated_sharpe"],
    )
    sc = _Screened(
        cand=Candidate(spec=spec, origin="evolution", lane="explore", operator="seed", rationale="r"),
        params={**fitted, "config_tag": "cfg"}, compiled=compiled, metrics=near.metrics,
        survival_score=0.0, proven=["bull"], venue_id="binance",
        per_symbol={
            "SOLUSDT": {"return": 0.061, "sharpe": 1.37, "max_drawdown": 0.12, "trades": 114.0},
            "XRPUSDT": {"return": -0.02, "sharpe": 0.3, "max_drawdown": 0.2, "trades": 50.0},
        },
        cells={"SOLUSDT": near, "XRPUSDT": dud},
    )
    with store.batch() as b:
        _ev, vid = loop._persist(sc, survival, None, b)

    verdicts = {
        r["symbol"]: r["verdict"]
        for r in store.rows("SELECT symbol, verdict FROM backtest_symbols WHERE strategy_version_id = ?", (vid,))
    }
    assert verdicts["SOLUSDT"] == WATCH_VERDICT
    assert verdicts["XRPUSDT"] == "deflated_sharpe"
    # The version is on the PAPER lane (so the funder + executor step it), not killed.
    sv = store.row("SELECT status, kill_reason FROM strategy_versions WHERE id = ?", (vid,))
    assert sv["status"] == "paper" and sv["kill_reason"] is None
    # passed_gates stays 0 — the gate verdict is unchanged.
    bt = store.row("SELECT passed_gates FROM backtests WHERE strategy_version_id = ? AND kind = 'screen'", (vid,))
    assert int(bt["passed_gates"]) == 0
    # Exactly one track — for the watch cell only; the lane='watch' tag is on its track_opened.
    tracks = store.rows("SELECT symbol FROM tracks WHERE strategy_version_id = ?", (vid,))
    assert [t["symbol"] for t in tracks] == ["SOLUSDT"]
    cid = cell_id(vid, "SOLUSDT", "binance")
    ev = store.row("SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ?", (cid,))
    assert ev is not None and '"lane": "watch"' in ev["payload"]
    # A watch cell starts the paper clock but never claims it passed the screen.
    assert store.row("SELECT COUNT(*) AS n FROM events WHERE kind='paper_started' AND ref_id=?", (cid,))["n"] == 1
    assert store.row("SELECT COUNT(*) AS n FROM events WHERE kind='screened_passed' AND ref_id=?", (cid,))["n"] == 0
