"""Phase 0 + 1: the honest wall (scorer) and the edge gate."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore, rolling_zscore
from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.data.universe_calendar import Listing, UniverseCalendar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.knowledge.store import Store
from cosmu.master.holdout import HoldoutLedger
from cosmu.master.scorer import (
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    expected_max_sharpe,
    probabilistic_sharpe,
    score,
)
from cosmu.research.fixtures import synthetic_gate_inputs
from cosmu.research.gate import evaluate_gate


def _store(tmp_path, name="wall") -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


# ---- A. Scorer math pinned to reference values ----------------------------------------------


def test_psr_is_half_when_sharpe_equals_benchmark():
    # PSR at SR* == SR_hat must be exactly 0.5 (z = 0), independent of n.
    assert abs(probabilistic_sharpe(0.1, 250, 0.0, 3.0, 0.1) - 0.5) < 1e-9


def test_psr_increases_with_observations():
    a = probabilistic_sharpe(0.1, 100, 0.0, 3.0, 0.0)
    b = probabilistic_sharpe(0.1, 1000, 0.0, 3.0, 0.0)
    assert 0.5 < a < b < 1.0


def test_negative_skew_lowers_psr():
    plain = probabilistic_sharpe(0.1, 250, 0.0, 3.0, 0.0)
    neg_skew = probabilistic_sharpe(0.1, 250, -1.0, 3.0, 0.0)
    assert neg_skew < plain  # fat left tail penalizes significance


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(0.01, 1) == 0.0
    few = expected_max_sharpe(0.01, 10)
    many = expected_max_sharpe(0.01, 10000)
    assert 0.0 < few < many


def test_deflated_sharpe_drops_as_trials_accumulate():
    metrics = BacktestMetrics(
        oos_return=Decimal("0.2"), sharpe=Decimal("2"), sortino=Decimal("2"),
        max_drawdown=Decimal("0.1"), win_rate=Decimal("0.6"), num_trades=50,
        sharpe_per_obs=Decimal("0.15"), skew=Decimal("0"), kurtosis=Decimal("3"), n_obs=300,
        pbo=Decimal("0.2"), trials_counted=1, folds_positive_pct=Decimal("0.8"),
        holdout_deflated_sharpe=Decimal("0.2"),
    )
    few = score(metrics, Settings().gates, trials=TrialStats(count=2, sr_variance=0.01))
    many = score(metrics, Settings().gates, trials=TrialStats(count=5000, sr_variance=0.01))
    assert few.deflated_sharpe_prob > many.deflated_sharpe_prob


def test_cscv_pbo_low_for_consistent_high_for_overfit():
    length = 64
    consistent = [[0.02] * length, [0.0] * length, [-0.02] * length]
    assert cscv_pbo(consistent) < 0.2

    half = length // 2
    overfit = [
        [0.03] * half + [-0.03] * half,  # great early, terrible late
        [-0.03] * half + [0.03] * half,  # mirror
    ]
    assert cscv_pbo(overfit) > 0.5


# ---- C. Survivorship-safe universe ----------------------------------------------------------


def test_universe_calendar_is_point_in_time():
    cal = UniverseCalendar([
        Listing("DEADUSDT", listed_at=datetime(2023, 1, 1, tzinfo=UTC), delisted_at=datetime(2023, 6, 1, tzinfo=UTC)),
        Listing("BTCUSDT", listed_at=datetime(2023, 1, 1, tzinfo=UTC)),
    ])
    assert "DEADUSDT" in cal.eligible(datetime(2023, 3, 1, tzinfo=UTC))  # present before delisting
    assert "DEADUSDT" not in cal.eligible(datetime(2023, 7, 1, tzinfo=UTC))  # gone after — no survivorship
    assert "BTCUSDT" in cal.eligible(datetime(2023, 7, 1, tzinfo=UTC))


# ---- D. One-shot holdout --------------------------------------------------------------------


def test_holdout_evaluates_once_and_locks(tmp_path):
    ledger = HoldoutLedger(_store(tmp_path, "holdout"))
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"deflated_sharpe": 0.9}

    first = ledger.evaluate_once("v1", compute)
    second = ledger.evaluate_once("v1", compute)
    assert first == second
    assert calls["n"] == 1  # second request returned the recorded verdict; holdout untouched
    assert ledger.consumed("v1")


# ---- E. Alt-data point-in-time + causal transform -------------------------------------------


def test_altdata_snapshots_are_point_in_time_and_append_only(tmp_path):
    store = AltDataStore(tmp_path / "altdata")
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    store.append("lc", "BTCUSDT", "galaxy_score", [AltDataPoint(ts=t0, available_at=t0 + timedelta(days=1), value=10.0)])
    # a later vendor revision of the SAME observation, available 5 days later
    store.append("lc", "BTCUSDT", "galaxy_score", [AltDataPoint(ts=t0, available_at=t0 + timedelta(days=5), value=99.0)])

    early = store.read_asof("lc", "BTCUSDT", "galaxy_score", t0 + timedelta(days=2))
    late = store.read_asof("lc", "BTCUSDT", "galaxy_score", t0 + timedelta(days=6))
    assert [p.value for p in early] == [10.0]  # revision not yet knowable
    assert [p.value for p in late] == [99.0]  # latest revision once available


def test_rolling_zscore_is_causal():
    z = rolling_zscore([float(x) for x in range(1, 41)], lookback=10)
    assert all(v is None for v in z[:9])  # warmup uses only past values
    assert z[-1] is not None


# ---- B. Capacity-aware costs ----------------------------------------------------------------


def _trending_bars(n=320, vol="100") -> list[Bar]:
    ts = datetime(2023, 1, 1, tzinfo=UTC)
    price = 100.0
    bars = []
    for i in range(n):
        move = 0.01 if i % 7 < 5 else -0.006
        open_ = price
        price = price * (1 + move)
        bars.append(Bar(
            ts=ts + timedelta(days=i), open=Decimal(str(round(open_, 4))),
            high=Decimal(str(round(max(open_, price) * 1.004, 4))),
            low=Decimal(str(round(min(open_, price) * 0.996, 4))),
            close=Decimal(str(round(price, 4))), volume=Decimal(vol),
        ))
    return bars


def test_capacity_costs_erode_returns_at_size():
    spec = seed_momentum_spec()
    params = fit_params(spec)
    market = {"BTCUSDT": _trending_bars()}
    # 1) Same size, more market impact => less net return (the cost model bites).
    no_impact = run_strategy_backtest(spec, params, market, fee_bps=Decimal("10"), impact_bps=Decimal("0"), size_multiplier=1.0)
    high_impact = run_strategy_backtest(spec, params, market, fee_bps=Decimal("10"), impact_bps=Decimal("500"), size_multiplier=1.0)
    assert no_impact.num_trades > 0
    assert no_impact.oos_return > high_impact.oos_return
    # 2) Under heavy impact, scaling size up raises participation and erodes the edge per trade.
    small = run_strategy_backtest(spec, params, market, fee_bps=Decimal("10"), impact_bps=Decimal("500"), size_multiplier=1.0)
    big = run_strategy_backtest(spec, params, market, fee_bps=Decimal("10"), impact_bps=Decimal("500"), size_multiplier=20.0)
    assert (small.oos_return / Decimal("1")) > (big.oos_return / Decimal("20"))  # return per unit deployed decays with size


# ---- F. The edge gate -----------------------------------------------------------------------


def test_gate_passes_on_edge_and_records_trials(tmp_path):
    store = _store(tmp_path, "gate_edge")
    market, provider = synthetic_gate_inputs(edge=True, seed=7)
    verdict = evaluate_gate(market, provider, store)
    assert verdict.decision == "PASS"
    assert verdict.deflated_sharpe_prob >= 0.95
    assert verdict.cscv_pbo < 0.5
    assert verdict.regimes_positive >= 2
    assert verdict.attempts == 12
    assert len(store.rows("SELECT 1 FROM trials")) == 12  # every attempt counted


def test_gate_stops_on_noise(tmp_path):
    store = _store(tmp_path, "gate_noise")
    market, provider = synthetic_gate_inputs(edge=False, seed=7)
    verdict = evaluate_gate(market, provider, store)
    assert verdict.decision == "STOP"
    assert verdict.reasons  # a real, explained falsification


def test_gate_is_deterministic(tmp_path):
    market, provider = synthetic_gate_inputs(edge=True, seed=7)
    a = evaluate_gate(market, provider, _store(tmp_path, "det_a"))
    b = evaluate_gate(market, provider, _store(tmp_path, "det_b"))
    assert (a.decision, a.deflated_sharpe_prob, a.cscv_pbo) == (b.decision, b.deflated_sharpe_prob, b.cscv_pbo)
