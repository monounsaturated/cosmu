# run_backtest_curve_retention nulls aged backtest_symbols.equity_curve_json (the recomputable per-cell curve
# cache) so the column stops re-bloating the hot DB, WITHOUT touching the per-symbol scalars. Offline sqlite.
# Pins: dry-run counts but changes nothing; apply nulls only rows older than keep_days; recent curves + all
# scalars survive; the pre-migration (no-column) DB is a no-op, never a crash.

from __future__ import annotations

import json

from cosmu.config.settings import Settings
from cosmu.data.backtest_curve_retention import run_backtest_curve_retention
from cosmu.knowledge.store import Store, reset_backtest_symbols_curve_cache


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/curve.sqlite3", openrouter_api_key=None))


def _cell(store: Store, *, symbol: str, created_at: str, curve: list[dict] | None) -> str:
    """Seed strategies→versions→backtests→backtest_symbols with a controlled created_at + optional curve."""
    sid = store.insert("strategies", {"name": f"s-{symbol}-{created_at}", "thesis": "t", "origin": "test", "created_at": created_at})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "s"}, "generated_code": "", "code_hash": f"h-{symbol}-{created_at}",
        "params": {}, "origin": "test", "status": "screened", "kind": "quant", "created_at": created_at,
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": created_at,
    })
    row = {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": "binance",
        "return_pct": "0.3", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "pass",
        "created_at": created_at,
    }
    if curve is not None:
        row["equity_curve_json"] = json.dumps(curve)
    store.insert("backtest_symbols", row)
    return vid


_CURVE = [{"ts": "2026-01-01T00:00:00+00:00", "net": 100_000.0}, {"ts": "2026-01-02T00:00:00+00:00", "net": 101_000.0}]
_NOW = "2026-07-01T00:00:00+00:00"  # keep_days=3 → cutoff 2026-06-28


def test_dry_run_counts_but_nulls_nothing(tmp_path):
    store = _store(tmp_path)
    _cell(store, symbol="OLD", created_at="2026-06-20T00:00:00+00:00", curve=_CURVE)   # aged
    _cell(store, symbol="NEW", created_at="2026-06-30T00:00:00+00:00", curve=_CURVE)   # fresh
    plan = run_backtest_curve_retention(settings=store.settings, store=store, keep_days=3, now_iso=_NOW, apply=False)
    assert plan["column_present"] and plan["to_null"] == 1 and plan["nulled"] == 0
    # nothing changed: both curves still present
    assert store.row("SELECT count(*) AS n FROM backtest_symbols WHERE equity_curve_json IS NOT NULL")["n"] == 2


def test_apply_nulls_only_aged_curves_and_keeps_scalars(tmp_path):
    store = _store(tmp_path)
    _cell(store, symbol="OLD", created_at="2026-06-20T00:00:00+00:00", curve=_CURVE)
    _cell(store, symbol="NEW", created_at="2026-06-30T00:00:00+00:00", curve=_CURVE)
    res = run_backtest_curve_retention(settings=store.settings, store=store, keep_days=3, now_iso=_NOW, apply=True)
    assert res["nulled"] == 1
    old = store.row("SELECT equity_curve_json, return_pct, sharpe, verdict FROM backtest_symbols WHERE symbol='OLD'")
    new = store.row("SELECT equity_curve_json FROM backtest_symbols WHERE symbol='NEW'")
    assert old["equity_curve_json"] is None            # aged curve dropped (recompute-on-view rebuilds it)
    assert new["equity_curve_json"] is not None        # fresh curve kept for a snappy sheet
    # the per-symbol SCALARS — the honest non-pooled visibility row — are untouched
    assert float(old["return_pct"]) == 0.3 and float(old["sharpe"]) == 1.0 and old["verdict"] == "pass"


def test_no_column_is_noop(tmp_path):
    store = _store(tmp_path)
    _cell(store, symbol="OLD", created_at="2026-06-20T00:00:00+00:00", curve=_CURVE)
    try:
        store.rows("ALTER TABLE backtest_symbols DROP COLUMN equity_curve_json")
    except Exception:  # noqa: BLE001 — old sqlite without DROP COLUMN; the guard is Postgres-relevant anyway
        import pytest

        pytest.skip("sqlite build lacks ALTER TABLE DROP COLUMN")
    reset_backtest_symbols_curve_cache()
    plan = run_backtest_curve_retention(settings=store.settings, store=store, keep_days=3, now_iso=_NOW, apply=True)
    assert plan["column_present"] is False and plan["to_null"] == 0 and plan["nulled"] == 0
    reset_backtest_symbols_curve_cache()
