# The funder must land capital on the verdict-PROVEN cell, not an arbitrary round-robin index. A gate-passed
# survivor screened on 5 crypto symbols, ROBUST only on SOLUSDT (negative/thin elsewhere), must fund SOLUSDT —
# NOT BTCUSDT (the round-robin pool[0]). Legacy versions with no per-symbol rows keep the round-robin fallback.
# This is the cardinal-sin fix: the per-symbol verdict (already computed at screen time) now STEERS the money.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.tracks import open_paper_track
from cosmu.orchestrator.loop import _survivor_tracks
from cosmu.spine.venue import default_catalog


def _store(tmp_path, name="fundv") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_survivor(store: Store, *, cells: list[tuple[str, str, float]] | None) -> str:
    """A gate-passed crypto survivor with a track + screen backtest. `cells` = [(symbol, verdict, sharpe)] written
    to backtest_symbols; None = legacy (no per-symbol rows). Returns the version_id."""
    with store.batch() as b:
        sid = b.insert("strategies", {"name": "Daily 6:30", "thesis": "t", "origin": "finder", "created_at": "2026-06-17T00:00:00Z"})
        vid = b.insert("strategy_versions", {
            "strategy_id": sid, "spec": {"name": "Daily 6:30", "universe": {"asset_classes": ["crypto"], "venues": ["binance"]}},
            "generated_code": "", "code_hash": "h", "params": {}, "origin": "finder", "status": "screened",
            "created_at": "2026-06-17T00:00:00Z",
        })
        bt = b.insert("backtests", {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5", "sortino": "1.5",
            "deflated_sharpe": "1.2", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 80, "pbo": "0.2",
            "trials_counted": 1, "folds_positive": 5, "passed_gates": 1, "holdout_passed": 1, "created_at": "2026-06-17T00:00:00Z",
        })
        for sym, verdict, sharpe in (cells or []):
            b.insert("backtest_symbols", {
                "backtest_id": bt, "strategy_version_id": vid, "symbol": sym, "venue_id": "binance",
                "return_pct": "0.1", "sharpe": str(sharpe), "max_drawdown": "0.05", "trades": 40,
                "verdict": verdict, "created_at": "2026-06-17T00:00:00Z",
            })
        open_paper_track(b, version_id=vid, starting_capital=Decimal("1000"))
    return vid


def test_funder_deploys_on_the_robust_symbol_not_round_robin(tmp_path):
    """SOLUSDT is the only ROBUST cell (BTC negative, ETH thin). The funder must pick SOLUSDT — proving capital
    follows the per-symbol verdict, not pool[0]=BTCUSDT (the old round-robin pick)."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[
        ("BTCUSDT", "negative", 0.1),
        ("ETHUSDT", "thin", 0.0),
        ("SOLUSDT", "robust", 2.0),
        ("XRPUSDT", "negative", 0.5),
    ])
    triples = _survivor_tracks(store, default_catalog())
    picked = {v: sym for (v, _track, sym, _venue) in triples}
    assert picked.get(vid) == "SOLUSDT", f"funder must deploy on the robust cell, got {picked.get(vid)}"


def test_funder_prefers_robust_over_higher_sharpe_fragile(tmp_path):
    """A FRAGILE cell with a huge Sharpe must NOT outrank a ROBUST cell — robustness (generalization) beats a
    lone best-of-N spike. ROBUST SOL (sharpe 1) is funded over FRAGILE BTC (sharpe 9)."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[("BTCUSDT", "fragile", 9.0), ("SOLUSDT", "robust", 1.0)])
    picked = {v: sym for (v, _t, sym, _vn) in _survivor_tracks(store, default_catalog())}
    assert picked.get(vid) == "SOLUSDT"


def test_legacy_version_without_per_symbol_rows_falls_back_to_round_robin(tmp_path):
    """A version with no backtest_symbols rows (legacy) must still fund — falling back to the round-robin pool —
    rather than being silently skipped."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=None)
    picked = {v: sym for (v, _t, sym, _vn) in _survivor_tracks(store, default_catalog())}
    assert picked.get(vid) in {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}  # round-robin pool member
