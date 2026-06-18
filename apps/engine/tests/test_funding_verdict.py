# BRUT fan-out: the funder fans out one paper track PER PASSING CELL (backtest_symbols.verdict='pass'), funding
# each cell on the EXACT symbol it was proven on — never a round-robin index, never a sibling-compared pick (the
# brut model has no siblings to compare). A 'fail' cell is never funded. Equity cells fund on the EXEC venue
# (alpaca), independent of the screen venue stored on the cell row.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.tracks import open_paper_track
from cosmu.orchestrator.loop import _survivor_tracks
from cosmu.spine.venue import default_catalog


def _store(tmp_path, name="fundv") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _seed_survivor(store: Store, *, cells: list[tuple[str, str]] | None, asset_classes=None, venues=None) -> str:
    """A gate-passed survivor with a screen backtest + backtest_symbols cells. `cells` = [(symbol, verdict)] where
    verdict is the BRUT per-cell 'pass'/'fail'. Returns the version_id."""
    asset_classes = asset_classes or ["crypto"]
    venues = venues or ["binance"]
    with store.batch() as b:
        sid = b.insert("strategies", {"name": "Daily 6:30", "thesis": "t", "origin": "finder", "created_at": "2026-06-18T00:00:00Z"})
        vid = b.insert("strategy_versions", {
            "strategy_id": sid, "spec": {"name": "Daily 6:30", "universe": {"asset_classes": asset_classes, "venues": venues}},
            "generated_code": "", "code_hash": "h", "params": {}, "origin": "finder", "status": "screened",
            "created_at": "2026-06-18T00:00:00Z",
        })
        bt = b.insert("backtests", {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.2", "sharpe": "1.5", "sortino": "1.5",
            "deflated_sharpe": "1.2", "max_dd": "0.1", "win_rate": "0.6", "num_trades": 80, "pbo": "0.2",
            "trials_counted": 1, "folds_positive": 5, "passed_gates": 1, "holdout_passed": 1, "created_at": "2026-06-18T00:00:00Z",
        })
        screen_venue = venues[0]
        for sym, verdict in (cells or []):
            b.insert("backtest_symbols", {
                "backtest_id": bt, "strategy_version_id": vid, "symbol": sym, "venue_id": screen_venue,
                "return_pct": "0.1", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 40,
                "verdict": verdict, "created_at": "2026-06-18T00:00:00Z",
            })
            if verdict == "pass":
                open_paper_track(b, version_id=vid, starting_capital=Decimal("1000"), symbol=sym, venue_id=screen_venue)
    return vid


def test_funder_fans_out_one_track_per_passing_cell(tmp_path):
    """Two cells pass (BTC, SOL), two fail (ETH, XRP). The funder fans out a track for EACH passing cell on its
    OWN symbol — never a single round-robin pick, never the failing cells."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[
        ("BTCUSDT", "pass"),
        ("ETHUSDT", "fail"),
        ("SOLUSDT", "pass"),
        ("XRPUSDT", "min_trades_per_symbol"),
    ])
    triples = _survivor_tracks(store, default_catalog())
    funded = {sym for (v, _t, sym, _vn) in triples if v == vid}
    assert funded == {"BTCUSDT", "SOLUSDT"}, f"funder must fan out per passing cell, got {funded}"


def test_funder_skips_a_version_with_no_passing_cell(tmp_path):
    """A survivor whose every cell FAILED the brut gate funds nothing — there is no 'pass' cell to fan out."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[("BTCUSDT", "fail"), ("ETHUSDT", "deflated_sharpe")])
    triples = _survivor_tracks(store, default_catalog())
    assert not [t for t in triples if t[0] == vid]


def test_each_passing_cell_funds_on_its_own_symbol(tmp_path):
    """A lone passing cell (SOL) funds on SOL — never on BTC by array position. The proven cell IS the funded
    cell (no cross-symbol reassignment)."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[("BTCUSDT", "fail"), ("SOLUSDT", "pass")])
    triples = _survivor_tracks(store, default_catalog())
    funded = [(sym, vn) for (v, _t, sym, vn) in triples if v == vid]
    assert funded == [("SOLUSDT", "binance")]


def test_equity_passing_cell_funds_on_alpaca_not_ibkr(tmp_path):
    """An equity passing cell funds on ALPACA (the venue with a real exec adapter), NOT the screen venue 'ibkr'
    (data-only). The brut model funds on the proven SYMBOL, routed to the exec venue for its asset class."""
    store = _store(tmp_path)
    vid = _seed_survivor(store, cells=[("SPY", "pass")], asset_classes=["equity"], venues=["ibkr"])
    triples = {v: (sym, venue) for (v, _t, sym, venue) in _survivor_tracks(store, default_catalog())}
    assert vid in triples, "equity passing cell must be funded (not skipped)"
    sym, venue = triples[vid]
    assert venue == "alpaca", f"equity must fund on alpaca (has exec adapter), got {venue}"
    assert sym == "SPY"
