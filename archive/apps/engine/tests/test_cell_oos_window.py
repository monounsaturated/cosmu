# The PER-CELL OOS window: each (strategy × symbol × venue) cell's CAGR ("Return /yr") must annualize THIS cell's
# standalone return over ITS OWN validation window — never the parent backtest's shared (longest-cell) window. A
# recently-listed coin (≈150 days) annualized over a sibling's 800-day window had a WRONG CAGR (the residual
# cross-window non-comparability). This covers: the day-span helper, the finder/loop PERSIST path (each cell's own
# window stored), the schema-adaptive write (pre-migration prod must not crash), and the READ path (_cell_row /
# /lab/symbols prefers the cell window, falling back to the parent backtest window only for legacy NULL cells).

from __future__ import annotations

from decimal import Decimal

import cosmu.api.routers.lab as lab_mod
from cosmu.config.settings import Settings
from cosmu.data.backtest import SymbolRun, cell_window_days
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store, reset_backtest_symbols_oos_window_cache
from cosmu.lab.finder import CellResult, StrategyFinder, VariantResult
from cosmu.master.scorer import BacktestMetrics
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec

try:  # the offline market fixture lives in the finder test; import it however the harness resolves `tests`
    from tests.test_lab_finder import _FixtureBars
except ModuleNotFoundError:  # collected without the rest of the suite (no `tests` namespace) → load by path
    import importlib.util
    import pathlib

    _spec = importlib.util.spec_from_file_location(
        "_tlf_fixture", pathlib.Path(__file__).with_name("test_lab_finder.py")
    )
    _tlf = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_tlf)
    _FixtureBars = _tlf._FixtureBars


def _store(tmp_path, name="celloos") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- the day-span helper


def _run(bar_ts: list[str]) -> SymbolRun:
    return SymbolRun(
        total_return=0.0, sharpe=0.0, sortino=0.0, max_drawdown=0.0, trades=[],
        bar_returns=[0.0] * len(bar_ts), bar_ts=bar_ts, fold_returns=[], regime_pnl={}, periods_per_year=365.0,
    )


def test_cell_window_days_spans_first_to_last_bar():
    """The window is the calendar-day span between the first and last validation bar timestamp."""
    assert cell_window_days(_run(["2026-01-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"])) == 90.0
    # A 'Z' suffix is accepted (treated as +00:00).
    assert cell_window_days(_run(["2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z"])) == 30.0


def test_cell_window_days_none_when_under_two_bars():
    """A degenerate run (0 or 1 bar) has nothing to span → None (honest unknown, rendered '—')."""
    assert cell_window_days(_run([])) is None
    assert cell_window_days(_run(["2026-01-01T00:00:00+00:00"])) is None


def test_cell_window_days_short_vs_long_window_differ():
    """The whole point: a 150-day cell and an 800-day cell get DIFFERENT windows (the fix)."""
    short = cell_window_days(_run(["2026-01-01T00:00:00+00:00", "2026-05-31T00:00:00+00:00"]))  # ~150d
    long = cell_window_days(_run(["2024-01-01T00:00:00+00:00", "2026-03-11T00:00:00+00:00"]))    # ~800d
    assert short is not None and long is not None
    assert long > short * 4  # not the same window — never annualized on a shared denominator


# --------------------------------------------------------------------------- the finder PERSIST path


def _finder(tmp_path) -> StrategyFinder:
    store = _store(tmp_path)
    return StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())


def test_finder_sweep_persists_per_cell_oos_window(tmp_path):
    """A full finder sweep computes each cell's OWN validation-window span and persists it to
    backtest_symbols.oos_window_days — the per-cell annualizer denominator."""
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)
    rows = finder.store.rows(
        "SELECT oos_window_days FROM backtest_symbols WHERE oos_window_days IS NOT NULL"
    )
    assert rows, "the sweep must persist at least one per-cell OOS window"
    assert all(float(r["oos_window_days"]) > 0 for r in rows)


def _killed_cell_variant(spec, *, window: float | None) -> VariantResult:
    """A single-cell variant that FAILS the gate (so _persist writes the backtest_symbols row WITHOUT the paper
    track / holdout machinery) but still carries an oos_window_days to persist."""
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    metrics = BacktestMetrics(
        oos_return=Decimal("-0.05"), sharpe=Decimal("0.2"), sortino=Decimal("0.2"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.4"), num_trades=12, regime_returns={},
    )
    cell = CellResult(
        symbol="BTCUSDT", venue_id="binance", metrics=metrics, deflated_sharpe=0.3, trades=12,
        passed=False, reasons=["deflated_sharpe"], oos_window_days=window,
    )
    return VariantResult(
        config_tag="cfg-oos", code_hash=compiled.code_hash, metrics=metrics, deflated_sharpe=0.3,
        profit_factor=0.5, net_profit=-0.05, gate_passed=False, reasons=["deflated_sharpe"], fitted_params=fitted,
        per_symbol={"BTCUSDT": {"return": -0.05, "sharpe": 0.2, "max_drawdown": 0.10, "trades": 12.0}},
        cells={"BTCUSDT": cell},
    )


def test_finder_persist_writes_oos_window_days(tmp_path):
    """Driving _persist directly: the cell's oos_window_days is written to backtest_symbols."""
    finder = _finder(tmp_path)
    spec = seed_orb_fvg_spec()
    variant = _killed_cell_variant(spec, window=150.0)
    finder._persist(spec, [variant], {}, default_catalog().venue("binance"))
    row = finder.store.row(
        "SELECT oos_window_days FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'",
        (variant.version_id,),
    )
    assert float(row["oos_window_days"]) == 150.0


def test_finder_persist_is_schema_adaptive_when_window_column_absent(tmp_path):
    """Pre-migration prod has no oos_window_days column. The persist must PROBE and skip the column (never crash
    the cohort write); the row still lands, just window-less."""
    finder = _finder(tmp_path)
    try:
        finder.store.rows("ALTER TABLE backtest_symbols DROP COLUMN oos_window_days")
    except Exception:  # noqa: BLE001 — older SQLite without DROP COLUMN: skip (prod is Postgres anyway)
        import pytest

        pytest.skip("sqlite build lacks ALTER TABLE DROP COLUMN")
    reset_backtest_symbols_oos_window_cache()
    spec = seed_orb_fvg_spec()
    variant = _killed_cell_variant(spec, window=150.0)
    finder._persist(spec, [variant], {}, default_catalog().venue("binance"))  # must NOT raise
    row = finder.store.row(
        "SELECT * FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", (variant.version_id,)
    )
    assert row is not None
    assert "oos_window_days" not in row.keys()  # the column was never written
    reset_backtest_symbols_oos_window_cache()  # don't leak the probe verdict to other tests


# --------------------------------------------------------------------------- the READ path (_cell_row / API)


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(lab_mod, "store", store)
    return TestClient(app_mod.app)


def _seed_cell(store, *, name, symbol, venue, return_pct, cell_window, oos_start, oos_end):
    """Persist a (strategy → version → backtest → backtest_symbols) chain with an explicit parent backtest window
    AND a per-cell window (None to leave the cell window NULL, exercising the legacy fallback)."""
    sid = store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": name}, "generated_code": "", "code_hash": "h" + name, "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "oos_start": oos_start, "oos_end": oos_end,
        "sharpe": "1.0", "sortino": "1.0", "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5",
        "num_trades": 30, "pbo": "0.2", "trials_counted": 1, "folds_positive": 4, "passed_gates": 1,
        "holdout_passed": 0, "created_at": "2026-06-17T00:00:00Z",
    })
    row = {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": str(return_pct), "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30,
        "verdict": "robust", "created_at": "2026-06-17T00:00:00Z",
    }
    if cell_window is not None:
        row["oos_window_days"] = cell_window
    store.insert("backtest_symbols", row)
    return vid


def test_cell_annualizes_over_its_own_window_not_the_parent(tmp_path, monkeypatch):
    """THE FIX: a short-history cell with its OWN ~180-day window annualizes the SAME return to a HIGHER CAGR than
    if it had been annualized over the parent's long (≈4yr) window — proving the per-cell window is used."""
    store = _store(tmp_path)
    # Same +20% return; the cell's OWN window is 180 days, while the parent backtest spans 2022-01..2025-12 (≈4yr).
    _seed_cell(store, name="Short", symbol="NEWCOIN", venue="binance", return_pct=0.20,
               cell_window=180.0, oos_start="2022-01", oos_end="2025-12")
    row = _client(monkeypatch, store).get("/lab/symbols?symbol=NEWCOIN").json()["rows"][0]
    assert row["oos_window_days"] == 180.0  # the CELL's own window, not the parent's ≈1460-day span
    # 1.20 ** (365.25/180) - 1 ≈ +0.435; over the parent's ≈4yr it would be ≈ +0.047 — wildly different.
    assert row["return_pct_annualized"] is not None
    assert row["return_pct_annualized"] > 0.30  # the SHORT-window CAGR, never the diluted long-window one


def test_legacy_cell_falls_back_to_parent_window(tmp_path, monkeypatch):
    """A legacy cell with a NULL own window falls back to the parent backtest's monthly bounds (so existing rows
    still annualize until the backfill / a re-screen fills their own window)."""
    store = _store(tmp_path)
    _seed_cell(store, name="Legacy", symbol="OLDCOIN", venue="binance", return_pct=0.20,
               cell_window=None, oos_start="2025-01", oos_end="2025-06")  # parent ≈6 months
    row = _client(monkeypatch, store).get("/lab/symbols?symbol=OLDCOIN").json()["rows"][0]
    # Fallback window = oos_window_days("2025-01","2025-06") = 6 months * 30 = 180 days.
    assert row["oos_window_days"] == 180.0
    assert row["return_pct_annualized"] is not None and row["return_pct_annualized"] > 0.30


def test_cell_window_honest_none_when_neither_exists(tmp_path, monkeypatch):
    """No cell window AND no parent bounds → oos_window_days None and return_pct_annualized None (rendered '—')."""
    store = _store(tmp_path)
    _seed_cell(store, name="NoWin", symbol="GHOST", venue="binance", return_pct=0.20,
               cell_window=None, oos_start=None, oos_end=None)
    row = _client(monkeypatch, store).get("/lab/symbols?symbol=GHOST").json()["rows"][0]
    assert row["oos_window_days"] is None
    assert row["return_pct_annualized"] is None
