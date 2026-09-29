# Aave on-chain money-market stress -> 24-72h vol-cascade lead — offline, deterministic, hermetic tests.
# No network, no live keys: the StressSeries + bars are INJECTED. Proves: (1) the rolling stress z-score is
# CAUSAL (uses only strictly-past values); (2) the PIT join never lets a stress value land on a bar before its
# UTC day; (3) the de-risk overlay charges the REAL maker fee on each step-out/step-in turn and steps flat for
# the pre-registered horizon; (4) the SymbolRun -> metrics_for_run -> promote_brut path runs and is judged BRUT
# per cell; (5) the disconfirmers (shuffle/lag placebo, partial-IC) are wired; (6) verdict resolution maps the
# pre-registered walls; (7) determinism.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.research.aave_stress import (
    HORIZON_DAYS,
    MAKER_FEE,
    STRESS_LOOKBACK,
    StressSeries,
    _align_stress_to_bars,
    _partial_ic,
    _rolling_z,
    _shuffle,
    _simulate_overlay,
    run_experiment,
)


def _bars(prices: list[float], *, start: datetime | None = None) -> list[Bar]:
    t0 = start or datetime(2024, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p, 4)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _stress(levels: list[float], *, start: datetime | None = None) -> StressSeries:
    t0 = start or datetime(2024, 1, 1, tzinfo=UTC)
    return StressSeries(dates=[t0 + timedelta(days=i) for i in range(len(levels))], level=levels, source="synthetic")


# --------------------------------------------------------------------------------------------------------------
# (1) causal rolling z-score: z[i] must depend ONLY on level[i-lookback:i]
# --------------------------------------------------------------------------------------------------------------
def test_rolling_z_is_causal_and_warms_up() -> None:
    lb = 5
    # a mildly noisy past (real APY is never perfectly flat -> a finite stdev) then a spike at index 10
    base = [1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.1, 0.9, 1.05, 0.95, 9.0, 1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.1]
    z = _rolling_z(base, lb)
    assert z[:lb] == [None] * lb, "z is undefined until the window fills"
    # the spike's OWN z (index 10) sees a noisy-but-small past window -> large positive z
    assert z[10] is not None and z[10] > 3.0
    # a perfectly FLAT past window has zero stdev -> z is the conservative 0.0 (never a spurious spike)
    flat = [1.0] * 18
    assert _rolling_z(flat, lb)[10] == 0.0
    # mutating a FUTURE value cannot change a past z (causality)
    fut = base[:]
    fut[15] = 999.0
    z2 = _rolling_z(fut, lb)
    assert z2[10] == z[10]


# --------------------------------------------------------------------------------------------------------------
# (2) PIT join: a stress value for day D may only land on bars whose UTC day >= D
# --------------------------------------------------------------------------------------------------------------
def test_pit_join_never_uses_future_stress() -> None:
    bars = _bars([100.0] * 6)
    stress = _stress([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    z = list(range(6))  # use the index as a stand-in "z" so we can read which day landed
    aligned = _align_stress_to_bars(bars, stress, [float(v) for v in z])
    # bar i (UTC day i) must carry stress day i (known by end of that day), never a later day
    for i in range(6):
        assert aligned[i] == float(i)
    # a stress series that STARTS later than the bars => the early bars carry None (no look-back into the future)
    late = _stress([1.0, 2.0], start=datetime(2024, 1, 4, tzinfo=UTC))
    aligned2 = _align_stress_to_bars(bars, late, [10.0, 20.0])
    assert aligned2[0] is None and aligned2[1] is None and aligned2[2] is None
    assert aligned2[3] == 10.0


# --------------------------------------------------------------------------------------------------------------
# (3) de-risk overlay: charges the maker fee on turns and goes flat for the horizon
# --------------------------------------------------------------------------------------------------------------
def test_overlay_steps_flat_for_horizon_and_charges_maker_fee() -> None:
    # flat prices so any equity change comes ONLY from fees; one spike at day 2
    bars = _bars([100.0] * 12)
    spike = [False, False, True, False, False, False, False, False, False, False, False, False]
    equity, bar_ts, trades = _simulate_overlay(bars, spike, horizon=HORIZON_DAYS, maker_fee=MAKER_FEE)
    # with flat prices, the ONLY effect is two maker-fee debits (step out + step back in) => equity drops by
    # ~ (1-fee)^2 of the base, never rises
    assert equity[-1] < equity[0]
    drag = 1.0 - equity[-1] / equity[0]
    assert abs(drag - (1.0 - (1 - MAKER_FEE) ** 2)) < 1e-9, "exactly two maker-fee turns on flat prices"
    # at least one closing trade recorded (the step-out closes the long)
    assert len(trades) >= 1
    assert len(bar_ts) == len(equity) - 1


def test_overlay_no_spike_is_buy_and_hold_minus_one_close() -> None:
    bars = _bars([100.0, 110.0, 121.0, 133.1])  # +10%/bar
    spike = [False] * 4
    equity, _, trades = _simulate_overlay(bars, spike, horizon=HORIZON_DAYS, maker_fee=0.0)
    # default-long the whole way, zero fee => equity tracks price exactly
    assert abs(equity[-1] / equity[0] - (133.1 / 100.0)) < 1e-6
    assert len(trades) == 1  # the single forced close at the end


# --------------------------------------------------------------------------------------------------------------
# (4)+(5)+(6) full experiment on injected data: runs the BRUT path + disconfirmers + verdict resolution
# --------------------------------------------------------------------------------------------------------------
def test_experiment_runs_brut_path_and_resolves_a_wall() -> None:
    n = 400
    # a gently trending price (so buy-and-hold is a real benchmark) + a noisy stress series with occasional spikes
    prices = [100.0 * (1.001 ** i) for i in range(n)]
    levels = []
    for i in range(n):
        v = 2.0 + 0.5 * ((i % 7) - 3)  # bounded oscillation
        if i % 53 == 0:
            v += 6.0  # periodic spike
        levels.append(v)
    market = {"BTCUSDT": _bars(prices)}
    stress = _stress(levels)
    v = run_experiment(stress=stress, market=market)
    assert v.decision in {"SURVIVOR", "KILL"}
    assert v.source == "synthetic"
    assert v.pit_honest is False  # synthetic is NOT the block-timestamped subgraph
    assert len(v.cells) == 1
    cell = v.cells[0]
    assert cell.symbol == "BTCUSDT" and cell.venue == "binance"
    # the brut gate produced a real DSR + trade count + reasons list
    assert 0.0 <= cell.deflated_sharpe_prob <= 1.0
    assert cell.num_trades >= 0
    # a periodic (non-vol-leading) stress spike on a smooth trend should NOT be a survivor
    assert v.decision == "KILL"
    assert v.wall in {"no_signal", "explained_by_vol_funding", "placebo_survives"}


def test_no_stress_data_is_honest_kill() -> None:
    v = run_experiment(stress=None, market={"BTCUSDT": _bars([100.0] * 200)})
    assert v.decision == "KILL" and v.wall == "no_stress_data" and v.pit_honest is False


def test_no_market_data_is_honest_kill() -> None:
    v = run_experiment(stress=_stress([2.0] * 100), market={})
    assert v.decision == "KILL" and v.wall == "no_market_data"


# --------------------------------------------------------------------------------------------------------------
# (5) disconfirmer mechanics: shuffle is a permutation; partial IC strips a control
# --------------------------------------------------------------------------------------------------------------
def test_shuffle_is_a_deterministic_permutation() -> None:
    vals = [float(i) for i in range(50)]
    a = _shuffle(vals, seed=42)
    b = _shuffle(vals, seed=42)
    assert a == b, "deterministic for a fixed seed"
    assert sorted(a) == sorted(vals), "a permutation — same multiset"
    assert a != vals, "actually shuffled"


def test_partial_ic_removes_a_collinear_control() -> None:
    # y is driven ENTIRELY by the control; x is a noisy copy of the control. After removing the control, x's
    # partial IC vs y must collapse toward zero (x adds nothing beyond the control).
    control = [float(i % 11) for i in range(120)]
    y = [c * 2.0 for c in control]
    x = [c + (0.01 * (i % 3)) for i, c in enumerate(control)]
    raw, partial, n = _partial_ic(x, y, [control])
    assert n == 120
    assert abs(raw) > 0.5, "raw IC is high (x ~ control ~ y)"
    assert abs(partial) < abs(raw), "partial IC is strictly smaller once the control is removed"


# --------------------------------------------------------------------------------------------------------------
# (7) determinism: same inputs -> same verdict
# --------------------------------------------------------------------------------------------------------------
def test_experiment_is_deterministic() -> None:
    n = 300
    prices = [100.0 * (1.0008 ** i) for i in range(n)]
    levels = [2.0 + (1.0 if i % 41 == 0 else 0.0) for i in range(n)]
    market = {"BTCUSDT": _bars(prices)}
    stress = _stress(levels)
    v1 = run_experiment(stress=stress, market=market)
    v2 = run_experiment(stress=stress, market=market)
    assert v1.decision == v2.decision and v1.wall == v2.wall
    assert [c.deflated_sharpe_prob for c in v1.cells] == [c.deflated_sharpe_prob for c in v2.cells]


def test_lookback_constant_is_sane() -> None:
    assert STRESS_LOOKBACK >= 10 and HORIZON_DAYS in (1, 2, 3, 4, 5)
