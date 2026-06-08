# Alpha-decay primitive: edge half-life + live-vs-funded drift → ANTICIPATORY defund (master/drift). The monitor
# is deterministic + offline + out of any LLM path; it pulls capital BEFORE realized P&L turns. Covers the pure
# analytics, the store readers over portfolio_snapshots, the audited monitor, and the rotation/portfolio wiring.

from __future__ import annotations

from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.drift import (
    aggregate_return_series,
    assess_drift,
    batch_track_return_series,
    fit_edge_decay,
    funded_track_ids,
    monitor_drift,
    rolling_edge,
    track_return_series,
)
from cosmu.master.portfolio import Portfolio
from cosmu.portfolio.rotation import Track, is_decayed, select_tracks


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
        _snap(store, "aggregate", "global", eq)
    for eq in ("1000", "1010", "1020"):
        _snap(store, "track", "v1", eq)
    pool = aggregate_return_series(store)
    sleeve = track_return_series(store, "v1")
    assert len(pool) == 2 and abs(pool[0] - 0.01) < 1e-9       # 100000 → 101000
    assert len(sleeve) == 2 and abs(sleeve[0] - 0.01) < 1e-9   # track scope isolated from aggregate


def test_batch_track_return_series_fetches_all_tracks_in_one_call(tmp_path):
    """batch_track_return_series returns the same series as N individual track_return_series calls;
    absent ids map to empty list (honest-empty, not an error)."""
    store = _store(tmp_path)
    for eq in ("1000", "1010", "1020"):
        _snap(store, "track", "vA", eq)
    for eq in ("500", "510"):
        _snap(store, "track", "vB", eq)
    # control: aggregate row must not leak into track results
    _snap(store, "aggregate", "global", "99999")

    result = batch_track_return_series(store, ["vA", "vB", "vMissing"])
    assert set(result.keys()) == {"vA", "vB", "vMissing"}
    # vA: 1000→1010→1020 → two returns of +1%
    assert len(result["vA"]) == 2 and abs(result["vA"][0] - 0.01) < 1e-9
    # vB: 500→510 → one return of +2%
    assert len(result["vB"]) == 1 and abs(result["vB"][0] - 0.02) < 1e-9
    # absent id → honest empty list
    assert result["vMissing"] == []
    # matches individual track_return_series for both present ids
    assert result["vA"] == track_return_series(store, "vA")
    assert result["vB"] == track_return_series(store, "vB")


def test_batch_track_return_series_empty_input(tmp_path):
    """batch_track_return_series with an empty list returns an empty dict without hitting the DB."""
    store = _store(tmp_path)
    assert batch_track_return_series(store, []) == {}


# --- audited monitor ------------------------------------------------------------------------------


def test_monitor_drift_audits_and_defunds(tmp_path):
    store = _store(tmp_path)
    # A decaying track trajectory (value still rising slightly each step but by less — edge dying).
    values = [1000.0]
    step = 30.0
    for _ in range(12):
        values.append(values[-1] + step)
        step *= 0.6
    for v in values:
        _snap(store, "track", "decayer", f"{v:.2f}")
    verdicts = monitor_drift(store, ["decayer"])
    assert len(verdicts) == 1 and verdicts[0].defund
    # both the per-track assessment and the defund decision are on the audit ledger
    assert store.row("SELECT 1 FROM events WHERE kind = 'drift_assessed' AND ref_id = 'decayer'") is not None
    assert store.row("SELECT 1 FROM events WHERE kind = 'track_defunded' AND ref_id = 'decayer'") is not None


# --- track lifecycle wiring -----------------------------------------------------------------------


def test_track_defunds_on_drift_flag_even_with_healthy_dsr():
    healthy = Track(id="ok", rolling_dsr=0.99)
    flagged = Track(id="drifting", rolling_dsr=0.99, drift_defund=True)
    assert not is_decayed(healthy)
    assert is_decayed(flagged)                            # anticipatory: pulled despite a still-high deflated Sharpe
    verdict = {v.version_id: v for v in select_tracks([healthy, flagged])}
    assert not verdict["drifting"].funded and "anticipatory" in verdict["drifting"].reason
    assert verdict["ok"].funded


def test_track_defunds_on_short_half_life():
    short = Track(id="dying", rolling_dsr=0.99, edge_half_life=1.5)
    assert is_decayed(short)
    assert not {v.version_id: v for v in select_tracks([short])}["dying"].funded


# --- portfolio accrual ----------------------------------------------------------------------------


def test_mark_to_market_accrues_per_track_series_without_polluting_aggregate(tmp_path):
    store = _store(tmp_path)
    pf = Portfolio(store)
    pf.apply_fill(instrument_id="binance:BTCUSDT", symbol="BTCUSDT", venue="binance", side=1,
                  qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="vA")
    pf.mark_to_market({"binance:BTCUSDT": Decimal("100")})
    pf.mark_to_market({"binance:BTCUSDT": Decimal("110")})
    # the aggregate reads stay aggregate-only (track rows don't leak into equity/high-water)
    assert pf.equity() > 0
    track = track_return_series(store, "vA")
    assert len(track) == 1 and abs(track[0] - 0.10) < 1e-6   # 100 → 110 marked value
    assert "vA" in funded_track_ids(store)


# --- read-only API surface ------------------------------------------------------------------------


def test_research_drift_endpoint_reports_funded_tracks(tmp_path):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_module

    store = _store(tmp_path)
    pf = Portfolio(store)
    pf.apply_fill(instrument_id="binance:BTCUSDT", symbol="BTCUSDT", venue="binance", side=1,
                  qty=Decimal("1"), price=Decimal("100"), fee=Decimal("0"), strategy_version_id="vEP")
    # a deteriorating trajectory across several marks (still positive, edge dying)
    for px in ("100", "108", "114", "117", "118.5", "119", "119.2", "119.3"):
        pf.mark_to_market({"binance:BTCUSDT": Decimal(px)})
    app_module.store = store
    body = TestClient(app_module.app).get("/research/drift").json()
    assert body["tracks"] and body["tracks"][0]["version_id"] == "vEP"
    assert "reason" in body["tracks"][0] and body["tracks"][0]["n"] >= 3
