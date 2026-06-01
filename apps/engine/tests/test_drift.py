# Alpha-decay primitive: edge half-life + live-vs-funded drift → ANTICIPATORY defund (master/drift). The monitor
# is deterministic + offline + out of any LLM path; it pulls capital BEFORE realized P&L turns. Covers the pure
# analytics, the store readers over portfolio_snapshots, the audited monitor, and the rotation/portfolio wiring.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.drift import (
    assess_drift,
    fit_edge_decay,
    funded_sleeve_ids,
    monitor_drift,
    pool_return_series,
    rolling_edge,
    sleeve_return_series,
)
from cosmu.master.portfolio import PaperPortfolio
from cosmu.portfolio.rotation import Sleeve, is_decayed, rotate


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/drift.sqlite3", openrouter_api_key=None))


# --- pure analytics -------------------------------------------------------------------------------


def test_fit_edge_decay_finds_finite_half_life_on_a_decaying_series():
    decaying = [0.02 - 0.0019 * i for i in range(11)]  # +0.02 → ~+0.001, still positive throughout
    decay = fit_edge_decay(rolling_edge(decaying, window=5))
    assert decay.slope < 0
    assert decay.current_edge > 0                       # edge not yet gone — this is the anticipatory window
    assert decay.half_life is not None and decay.half_life > 0
    assert decay.periods_to_zero is not None and decay.periods_to_zero > 0


def test_fit_edge_decay_no_half_life_when_flat_or_rising():
    assert fit_edge_decay([0.01, 0.01, 0.01, 0.01, 0.01]).half_life is None
    assert fit_edge_decay([0.001, 0.005, 0.01, 0.02]).half_life is None  # rising


def test_assess_drift_healthy_edge_is_not_defunded():
    steady = [0.01] * 12
    v = assess_drift("s1", steady)
    assert not v.defund
    assert "healthy" in v.reason


def test_assess_drift_defunds_a_decaying_edge_before_pnl_turns():
    # Declines from strong to barely-positive: mean is STILL POSITIVE (P&L hasn't turned) but the edge is dying.
    decaying = [0.02 - 0.0019 * i for i in range(11)]
    v = assess_drift("s2", decaying)
    assert v.drift.realized_edge > 0                    # we are pulling capital while still nominally in profit
    assert v.defund
    assert ("half-life" in v.reason) or ("below" in v.reason) or ("CUSUM" in v.reason)


def test_assess_drift_cusum_flags_a_downward_change_point():
    # Funded baseline ~+0.02, then a sustained shift down to ~+0.001 — CUSUM should accumulate and alarm.
    series = [0.02] * 6 + [0.001] * 8
    v = assess_drift("s3", series, cusum_h=5.0)
    assert v.drift.cusum_alarm
    assert v.defund


def test_assess_drift_insufficient_history_never_defunds():
    v = assess_drift("s4", [0.01, -0.2])
    assert not v.defund
    assert "insufficient" in v.reason


def test_assess_drift_explicit_backtest_reference_is_labelled():
    v = assess_drift("s5", [0.001] * 8, reference_edge=0.02)
    assert v.drift.reference == "backtest"
    assert v.defund  # realized far below the backtest edge it was funded on


# --- store readers --------------------------------------------------------------------------------


def _snap(store: Store, scope: str, ref_id: str, equity: str) -> None:
    store.insert(
        "portfolio_snapshots",
        {"scope": scope, "ref_id": ref_id, "ts": utcnow(), "equity": equity, "cash": "0", "positions_value": equity, "pnl": "0", "drawdown": "0"},
    )


def test_store_readers_derive_returns_and_isolate_scopes(tmp_path):
    store = _store(tmp_path)
    for eq in ("100000", "101000", "100500"):
        _snap(store, "pool", "global", eq)
    for eq in ("1000", "1010", "1020"):
        _snap(store, "sleeve", "v1", eq)
    pool = pool_return_series(store)
    sleeve = sleeve_return_series(store, "v1")
    assert len(pool) == 2 and abs(pool[0] - 0.01) < 1e-9       # 100000 → 101000
    assert len(sleeve) == 2 and abs(sleeve[0] - 0.01) < 1e-9   # sleeve scope isolated from pool


# --- audited monitor ------------------------------------------------------------------------------


def test_monitor_drift_audits_and_defunds(tmp_path):
    store = _store(tmp_path)
    # A decaying sleeve trajectory (value still rising slightly each step but by less — edge dying).
    values = [1000.0]
    step = 30.0
    for _ in range(12):
        values.append(values[-1] + step)
        step *= 0.6
    for v in values:
        _snap(store, "sleeve", "decayer", f"{v:.2f}")
    verdicts = monitor_drift(store, ["decayer"])
    assert len(verdicts) == 1 and verdicts[0].defund
    # both the per-sleeve assessment and the defund decision are on the audit ledger
    assert store.row("SELECT 1 FROM events WHERE kind = 'drift_assessed' AND ref_id = 'decayer'") is not None
    assert store.row("SELECT 1 FROM events WHERE kind = 'sleeve_defunded' AND ref_id = 'decayer'") is not None


# --- rotation wiring ------------------------------------------------------------------------------


def test_rotation_defunds_on_drift_flag_even_with_healthy_dsr():
    healthy = Sleeve(id="ok", edge=0.05, variance=0.01, rolling_dsr=0.99)
    flagged = Sleeve(id="drifting", edge=0.05, variance=0.01, rolling_dsr=0.99, drift_defund=True)
    assert not is_decayed(healthy)
    assert is_decayed(flagged)                            # anticipatory: pulled despite a still-high deflated Sharpe
    allocs = {a.sleeve_id: a for a in rotate([healthy, flagged])}
    assert allocs["drifting"].weight == 0.0 and "anticipatory" in allocs["drifting"].reason
    assert allocs["ok"].weight > 0.0


def test_rotation_defunds_on_short_half_life():
    short = Sleeve(id="dying", edge=0.05, variance=0.01, rolling_dsr=0.99, edge_half_life=1.5)
    assert is_decayed(short)
    assert {a.sleeve_id: a.weight for a in rotate([short])}["dying"] == 0.0


# --- portfolio accrual ----------------------------------------------------------------------------


def test_mark_to_market_accrues_per_sleeve_series_without_polluting_pool(tmp_path):
    store = _store(tmp_path)
    pf = PaperPortfolio(store)
    pf.apply_fill(instrument_id="binance:BTCUSDT", symbol="BTCUSDT", venue="binance", side=1,
                  qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="vA")
    pf.mark_to_market({"binance:BTCUSDT": Decimal("100")})
    pf.mark_to_market({"binance:BTCUSDT": Decimal("110")})
    # the pool reads stay pool-only (sleeve rows don't leak into equity/high-water)
    assert pf.equity() > 0
    sleeve = sleeve_return_series(store, "vA")
    assert len(sleeve) == 1 and abs(sleeve[0] - 0.10) < 1e-6   # 100 → 110 marked value
    assert "vA" in funded_sleeve_ids(store)


# --- read-only API surface ------------------------------------------------------------------------


def test_research_drift_endpoint_reports_funded_sleeves(tmp_path):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_module

    store = _store(tmp_path)
    pf = PaperPortfolio(store)
    pf.apply_fill(instrument_id="binance:BTCUSDT", symbol="BTCUSDT", venue="binance", side=1,
                  qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="vEP")
    # a deteriorating trajectory across several marks (still positive, edge dying)
    for px in ("100", "108", "114", "117", "118.5", "119", "119.2", "119.3"):
        pf.mark_to_market({"binance:BTCUSDT": Decimal(px)})
    app_module.store = store
    body = TestClient(app_module.app).get("/research/drift").json()
    assert body["sleeves"] and body["sleeves"][0]["version_id"] == "vEP"
    assert "reason" in body["sleeves"][0] and body["sleeves"][0]["n"] >= 3
