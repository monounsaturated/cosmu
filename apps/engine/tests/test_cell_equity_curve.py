# The PER-CELL backtest equity curve: each (strategy × symbol × venue) cell's OWN net-of-fee equity trajectory —
# the cumulated per-bar returns its metrics scored on — persisted to backtest_symbols.equity_curve_json at screen
# time and served per-cell so the strat sheet draws a real net-equity curve for a backtest-only combo (no fills).
# Covers: the cumulation helper, the finder PERSIST path (full sweep + direct), the SERVE endpoint, and the
# schema-adaptive write (a pre-migration prod with no column must never crash the persist).

from __future__ import annotations

import json
from decimal import Decimal

import cosmu.api.routers.strategies as strat_mod
from cosmu.config.settings import Settings
from cosmu.data.backtest import SymbolRun, equity_curve_points
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store, reset_backtest_symbols_curve_cache
from cosmu.lab.finder import CellResult, StrategyFinder, VariantResult
from cosmu.master.scorer import BacktestMetrics
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec


class _FixtureBars:
    """Small, fast OFFLINE market provider for the finder sweep — 2 catalog symbols × ~280 edge-bearing bars (the
    screen's 80-bar floor + holdout split). Built on the PACKAGE-level fixture (cosmu.research.fixtures) so this
    test never cross-imports another test module (which doesn't resolve as a package under the default pytest
    import mode). Mirrors the same helper in test_lab_finder."""

    def __init__(self) -> None:
        full = edge_bearing_screen_market(n=280)
        self._by = {sym: full[sym][-280:] for sym in ("BTCUSDT", "ETHUSDT")}
        self._default = self._by["BTCUSDT"]

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by.get(symbol, self._default)[-limit:]


def _store(tmp_path, name="cellcurve") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- the cumulation helper


def _run(bar_returns: list[float], bar_ts: list[str]) -> SymbolRun:
    return SymbolRun(
        total_return=0.0, sharpe=0.0, sortino=0.0, max_drawdown=0.0, trades=[],
        bar_returns=bar_returns, bar_ts=bar_ts, fold_returns=[], regime_pnl={}, periods_per_year=365.0,
    )


def test_equity_curve_points_cumulates_net_of_fee_returns_paired_with_ts():
    """The curve is (1 + bar_returns) cumulated from the sim base, point i paired with bar_ts[i] — exactly the
    net-of-fee mark-to-market equity the cell's metrics derive from, never gross/pre-cost."""
    run = _run([0.01, -0.005, 0.02], ["t0", "t1", "t2"])
    pts = equity_curve_points(run, base=100_000.0)
    assert [p["ts"] for p in pts] == ["t0", "t1", "t2"]
    assert pts[0]["net"] == round(100_000.0 * 1.01, 4) == 101_000.0
    assert pts[1]["net"] == round(101_000.0 * 0.995, 4) == 100_495.0
    assert pts[2]["net"] == round(100_495.0 * 1.02, 4)


def test_equity_curve_points_empty_when_no_timestamps():
    """A degenerate run with no bar timestamps yields no points (honest empty — the curve renders its empty state),
    and the length is bounded by the shorter of bar_returns / bar_ts (never an index error)."""
    assert equity_curve_points(_run([0.01, 0.02], [])) == []
    # Mismatched lengths: pair only what's aligned, drop the unlabelled tail.
    assert len(equity_curve_points(_run([0.01, 0.02, 0.03], ["t0", "t1"]))) == 2


# --------------------------------------------------------------------------- the finder PERSIST path


def _finder(tmp_path) -> StrategyFinder:
    store = _store(tmp_path)
    return StrategyFinder(settings=store.settings, store=store, market_data=_FixtureBars())


def test_finder_sweep_persists_per_cell_equity_curve(tmp_path):
    """A full finder sweep cumulates each cell's bar_returns and persists the curve to
    backtest_symbols.equity_curve_json — the queryable per-cell net-equity series the sheet draws from."""
    finder = _finder(tmp_path)
    finder.find(seed_orb_fvg_spec(), max_variants=8)
    rows = finder.store.rows(
        "SELECT equity_curve_json FROM backtest_symbols WHERE equity_curve_json IS NOT NULL"
    )
    assert rows, "the sweep must persist at least one per-cell equity curve"
    curve = json.loads(rows[0]["equity_curve_json"])
    assert len(curve) >= 2  # a drawable line
    assert all("ts" in p and "net" in p for p in curve)
    # The curve is the net-of-fee equity (a finite series moving off the sim base), never a constant.
    nets = [p["net"] for p in curve]
    assert all(isinstance(v, (int, float)) for v in nets)
    assert len(set(nets)) > 1


def _killed_cell_variant(spec, *, curve: list[dict]) -> tuple[VariantResult, BacktestMetrics]:
    """A single-cell variant that FAILS the gate (so _persist writes the backtest_symbols row WITHOUT the paper
    track / holdout machinery) but still carries an equity_curve to persist."""
    fitted = fit_params(spec)
    compiled = compile_spec(spec, fitted)
    metrics = BacktestMetrics(
        oos_return=Decimal("-0.05"), sharpe=Decimal("0.2"), sortino=Decimal("0.2"),
        max_drawdown=Decimal("0.10"), win_rate=Decimal("0.4"), num_trades=12, regime_returns={},
    )
    cell = CellResult(
        symbol="BTCUSDT", venue_id="binance", metrics=metrics, deflated_sharpe=0.3, trades=12,
        passed=False, reasons=["deflated_sharpe"], equity_curve=curve,
    )
    variant = VariantResult(
        config_tag="cfg-curve", code_hash=compiled.code_hash, metrics=metrics, deflated_sharpe=0.3,
        profit_factor=0.5, net_profit=-0.05, gate_passed=False, reasons=["deflated_sharpe"], fitted_params=fitted,
        per_symbol={"BTCUSDT": {"return": -0.05, "sharpe": 0.2, "max_drawdown": 0.10, "trades": 12.0}},
        cells={"BTCUSDT": cell},
    )
    return variant, metrics


def test_finder_persist_writes_equity_curve_json(tmp_path):
    """Driving _persist directly: the cell's equity_curve is serialized to backtest_symbols.equity_curve_json."""
    finder = _finder(tmp_path)
    spec = seed_orb_fvg_spec()
    curve = [{"ts": "2026-01-01T00:00:00+00:00", "net": 100_500.0}, {"ts": "2026-01-02T00:00:00+00:00", "net": 101_250.0}]
    variant, _ = _killed_cell_variant(spec, curve=curve)
    finder._persist(spec, [variant], {}, default_catalog().venue("binance"))
    vid = variant.version_id
    assert vid is not None
    row = finder.store.row(
        "SELECT equity_curve_json FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", (vid,)
    )
    assert row["equity_curve_json"]
    assert json.loads(row["equity_curve_json"]) == curve


def test_finder_persist_is_schema_adaptive_when_column_absent(tmp_path):
    """Pre-migration prod has no equity_curve_json column. The persist must PROBE and skip the column (never
    crash the whole cohort write); the row still lands, just curve-less."""
    finder = _finder(tmp_path)
    # Simulate pre-migration prod: drop the column, then force a re-probe.
    try:
        finder.store.rows("ALTER TABLE backtest_symbols DROP COLUMN equity_curve_json")
    except Exception:  # noqa: BLE001 — older SQLite without DROP COLUMN: skip (the prod path is Postgres anyway)
        import pytest

        pytest.skip("sqlite build lacks ALTER TABLE DROP COLUMN")
    reset_backtest_symbols_curve_cache()
    spec = seed_orb_fvg_spec()
    variant, _ = _killed_cell_variant(spec, curve=[{"ts": "t0", "net": 100_500.0}, {"ts": "t1", "net": 101_000.0}])
    finder._persist(spec, [variant], {}, default_catalog().venue("binance"))  # must NOT raise
    vid = variant.version_id
    row = finder.store.row("SELECT * FROM backtest_symbols WHERE strategy_version_id = ? AND symbol = 'BTCUSDT'", (vid,))
    assert row is not None  # the row landed
    assert "equity_curve_json" not in row.keys()  # the column was never written
    reset_backtest_symbols_curve_cache()  # don't leak the probe verdict to other tests


# --------------------------------------------------------------------------- the SERVE endpoint


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(strat_mod, "store", store)
    return TestClient(app_mod.app)


def _algo(store: Store, name: str = "A") -> str:
    return store.insert("strategies", {"name": name, "thesis": "t", "origin": "test", "created_at": "2026-06-18T00:00:00Z"})


def _version_with_cell(store: Store, *, symbol: str, venue: str | None, curve: list[dict] | None) -> str:
    sid = _algo(store)
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "s"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-18T00:00:00Z",
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0, "created_at": "2026-06-18T00:00:00Z",
    })
    row = {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": "0.3", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "pass",
        "created_at": "2026-06-18T00:00:00Z",
    }
    if curve is not None:
        row["equity_curve_json"] = json.dumps(curve)
    store.insert("backtest_symbols", row)
    return vid


def test_cell_curve_serves_persisted_points(tmp_path, monkeypatch):
    """GET /strategies/{vid}/cell-curve?symbol=&venue= returns THAT cell's stored net-equity points, available."""
    store = _store(tmp_path)
    curve = [{"ts": "2026-01-01T00:00:00+00:00", "net": 100_000.0}, {"ts": "2026-01-02T00:00:00+00:00", "net": 101_500.0}]
    vid = _version_with_cell(store, symbol="BTCUSDT", venue="binance", curve=curve)
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert body["available"] is True
    assert body["symbol"] == "BTCUSDT" and body["venue"] == "binance"
    assert [(p["ts"], p["net"]) for p in body["points"]] == [(p["ts"], p["net"]) for p in curve]


def test_cell_curve_honest_empty_when_no_curve_stored(tmp_path, monkeypatch):
    """A cell with no stored curve (NULL column) → available=False, points=[] — an honest empty, never fabricated."""
    store = _store(tmp_path)
    vid = _version_with_cell(store, symbol="ETHUSDT", venue="binance", curve=None)
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=ETHUSDT&venue=binance").json()
    assert body["available"] is False and body["points"] == []


def test_cell_curve_addresses_null_venue_cell_with_empty_venue(tmp_path, monkeypatch):
    """venue="" addresses the NULL-venue cell explicitly (mirrors the /triplet selector), never silently skipped."""
    store = _store(tmp_path)
    curve = [{"ts": "t0", "net": 100_000.0}, {"ts": "t1", "net": 100_900.0}]
    vid = _version_with_cell(store, symbol="BTCUSDT", venue=None, curve=curve)
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=").json()
    assert body["available"] is True and len(body["points"]) == 2


def test_cell_curve_empty_when_column_absent(tmp_path, monkeypatch):
    """Pre-migration prod (no equity_curve_json column) → the endpoint returns an honest empty curve (it never
    SELECTs a non-existent column and crashes)."""
    store = _store(tmp_path)
    vid = _version_with_cell(store, symbol="BTCUSDT", venue="binance", curve=[{"ts": "t0", "net": 1.0}, {"ts": "t1", "net": 2.0}])
    try:
        store.rows("ALTER TABLE backtest_symbols DROP COLUMN equity_curve_json")
    except Exception:  # noqa: BLE001
        import pytest

        pytest.skip("sqlite build lacks ALTER TABLE DROP COLUMN")
    reset_backtest_symbols_curve_cache()
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert body["available"] is False and body["points"] == []
    reset_backtest_symbols_curve_cache()


# ------------------------------------------------------------------ the RECOMPUTE-ON-DEMAND fallback (NULL curve)
# Existing cells (the bulk of prod) were screened BEFORE equity_curve_json shipped, so the column is NULL. The
# endpoint must recompute the curve on the fly from the version's spec over the cell's bars (and cache it back),
# never show "No backtest curve". These tests inject an OFFLINE bar provider so the recompute is deterministic.


def _runnable_version_null_curve(store: Store, *, symbol: str, venue: str | None) -> str:
    """Seed a version with a REAL runnable spec (seed_orb_fvg_spec) + a backtest_symbols cell whose
    equity_curve_json is NULL — the existing-prod-cell shape the recompute path must populate."""
    spec = seed_orb_fvg_spec()
    sid = _algo(store)
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": spec.model_dump(mode="json"), "generated_code": "", "code_hash": "h",
        "params": fit_params(spec), "origin": "test", "status": "screened", "kind": "quant",
        "created_at": "2026-06-18T00:00:00Z",
    })
    bt = store.insert("backtests", {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": "1.0", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 30, "pbo": "0.2",
        "trials_counted": 1, "folds_positive": 4, "passed_gates": 1, "holdout_passed": 0,
        "venue_id": venue, "fee_bps": "10", "slippage_bps": "5", "impact_bps": "40",
        "created_at": "2026-06-18T00:00:00Z",
    })
    store.insert("backtest_symbols", {
        "backtest_id": bt, "strategy_version_id": vid, "symbol": symbol, "venue_id": venue,
        "return_pct": "0.3", "sharpe": "1.0", "max_drawdown": "0.05", "trades": 30, "verdict": "pass",
        "created_at": "2026-06-18T00:00:00Z",  # NB: NO equity_curve_json → NULL, the existing-cell shape
    })
    return vid


def _patch_offline_bars(monkeypatch, *, symbol: str, venue: str, bars):
    """Make the recompute's build_crypto_cells return ONE offline PriceCell for (symbol, venue) — no network."""
    from cosmu.data import price_cells as pc_mod

    def _fake_build(store, *, timeframe, limit, enabled_venues=None, reference=None, persist=True, fallback_symbols=()):  # noqa: ANN001, ARG001
        return [pc_mod.PriceCell(key=pc_mod.cell_key(symbol, venue), symbol=symbol, venue_id=venue,
                                 bars=bars, reuses_reference=(venue == "binance"))]

    monkeypatch.setattr(pc_mod, "build_crypto_cells", _fake_build)


def test_cell_curve_recomputes_when_curve_null(tmp_path, monkeypatch):
    """A cell with a NULL stored curve but a runnable spec → the endpoint RECOMPUTES a non-empty net-of-fee curve
    from the cell's bars (so an existing backtest combo's sheet draws a real curve, never 'No backtest curve')."""
    store = _store(tmp_path)
    vid = _runnable_version_null_curve(store, symbol="BTCUSDT", venue="binance")
    _patch_offline_bars(monkeypatch, symbol="BTCUSDT", venue="binance", bars=_FixtureBars().fetch_bars("BTCUSDT", "1h", limit=1000))
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert body["available"] is True
    assert len(body["points"]) >= 2
    nets = [p["net"] for p in body["points"]]
    assert all(isinstance(v, (int, float)) for v in nets)
    assert len(set(nets)) > 1  # a real net-of-fee trajectory, never a constant


def test_cell_curve_recompute_caches_back_to_row(tmp_path, monkeypatch):
    """The recomputed curve is WRITTEN BACK to backtest_symbols.equity_curve_json so the next request is cached
    (no second backtest). After the first GET the row carries the curve; a second GET serves it directly."""
    store = _store(tmp_path)
    vid = _runnable_version_null_curve(store, symbol="BTCUSDT", venue="binance")
    _patch_offline_bars(monkeypatch, symbol="BTCUSDT", venue="binance", bars=_FixtureBars().fetch_bars("BTCUSDT", "1h", limit=1000))
    client = _client(monkeypatch, store)
    first = client.get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert first["available"] is True
    row = store.row("SELECT equity_curve_json FROM backtest_symbols WHERE strategy_version_id = ?", (vid,))
    assert row["equity_curve_json"], "the recomputed curve must be cached back to the row"
    cached = json.loads(row["equity_curve_json"])
    assert [(p["ts"], p["net"]) for p in cached] == [(p["ts"], p["net"]) for p in first["points"]]
    # A second request with the bar provider made empty still serves the (now cached) curve — proof it didn't re-run.
    _patch_offline_bars(monkeypatch, symbol="BTCUSDT", venue="binance", bars=[])
    second = client.get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert second["available"] is True and len(second["points"]) == len(first["points"])


def test_cell_curve_honest_empty_when_recompute_has_no_bars(tmp_path, monkeypatch):
    """When the cell's bars are unavailable (offline / delisted) the recompute yields nothing → honest empty
    (available=False), never a fabricated curve."""
    store = _store(tmp_path)
    vid = _runnable_version_null_curve(store, symbol="BTCUSDT", venue="binance")
    _patch_offline_bars(monkeypatch, symbol="BTCUSDT", venue="binance", bars=[])  # no bars at all
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=BTCUSDT&venue=binance").json()
    assert body["available"] is False and body["points"] == []


def test_cell_curve_honest_empty_when_spec_unparseable(tmp_path, monkeypatch):
    """A legacy/malformed spec can't be re-run → the recompute returns honest empty rather than crashing the
    endpoint (the existing placeholder-spec NULL-curve cell exercises exactly this fallback branch)."""
    store = _store(tmp_path)
    vid = _version_with_cell(store, symbol="ETHUSDT", venue="binance", curve=None)  # spec={"name":"s"} = unparseable
    body = _client(monkeypatch, store).get(f"/strategies/{vid}/cell-curve?symbol=ETHUSDT&venue=binance").json()
    assert body["available"] is False and body["points"] == []
