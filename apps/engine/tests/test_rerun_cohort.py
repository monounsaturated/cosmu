# intent: pin the THREE new pieces of the honest re-run harness — (1) the per-bar exposure seam in
# data/backtest.py (a None size_series is byte-identical to the scalar multiplier; a tilt scales notional
# WITHOUT adding/removing trades), (2) the slow btc_social_regime (research/social_norm.slow_social_regime:
# low-turnover, hysteresis + min-dwell, point-in-time on availability), and (3) the size-series mapping +
# dwell-preserving time-shuffle placebo in research/rerun_cohort. ZERO network: all data is synthetic fixtures.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.altdata import AltDataPoint
from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_momentum_spec
from cosmu.research.rerun_cohort import (
    _TILT_HI,
    _TILT_LO,
    _shuffle_regime_preserving_dwell,
    _size_series_from_regime,
)
from cosmu.research.social_norm import _ewma, slow_social_regime


def _trending_bars(n: int = 320, vol: str = "100") -> list[Bar]:
    ts = datetime(2023, 1, 1, tzinfo=UTC)
    price = 100.0
    bars: list[Bar] = []
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


# ---- (1) the per-bar exposure seam ----------------------------------------------------------------


def test_none_size_series_is_byte_identical_to_scalar():
    """A None size_series must reproduce the per-run scalar multiplier EXACTLY — every existing spec unchanged."""
    spec = seed_momentum_spec()
    params = fit_params(spec)
    market = {"BTCUSDT": _trending_bars()}
    scalar = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), size_multiplier=1.0)
    none_series = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=Decimal("10"), size_multiplier=1.0, size_series=None
    )
    assert scalar.metrics.oos_return == none_series.metrics.oos_return
    assert scalar.metrics.num_trades == none_series.metrics.num_trades
    assert scalar.val_returns == none_series.val_returns


def test_full_one_size_series_equals_scalar_one():
    """A size_series that is 1.0 on EVERY bar must equal the scalar-1.0 run (the seam reads it per bar)."""
    spec = seed_momentum_spec()
    params = fit_params(spec)
    bars = _trending_bars()
    market = {"BTCUSDT": bars}
    ones = {b.ts.isoformat(): 1.0 for b in bars}
    scalar = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), size_multiplier=1.0)
    series = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), size_series=ones)
    assert scalar.metrics.oos_return == series.metrics.oos_return
    assert scalar.metrics.num_trades == series.metrics.num_trades


def test_size_tilt_changes_exposure_not_trade_count():
    """A market-wide DOWN-tilt scales the notional (less return-per-unit) but must NOT add or remove trades —
    the regime overlay only changes exposure, never the entry/exit decisions."""
    spec = seed_momentum_spec()
    params = fit_params(spec)
    bars = _trending_bars()
    market = {"BTCUSDT": bars}
    full = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), size_multiplier=1.0)
    half = {b.ts.isoformat(): 0.5 for b in bars}
    tilted = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("10"), size_series=half)
    assert full.metrics.num_trades > 0
    assert tilted.metrics.num_trades == full.metrics.num_trades  # SAME trades — only exposure changed
    # half the exposure ⇒ strictly smaller absolute return magnitude (this trending book is net-positive)
    assert abs(float(tilted.metrics.oos_return)) < abs(float(full.metrics.oos_return))


# ---- (2) the slow btc_social_regime ----------------------------------------------------------------


def _accel_series(values: list[float]) -> list[AltDataPoint]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i + 1), value=v)
            for i, v in enumerate(values)]


def test_ewma_is_causal_and_inherits_availability():
    pts = _accel_series([1.0, 1.0, 1.0, 10.0])
    out = _ewma(pts, 3)
    assert len(out) == len(pts)
    assert out[0].value == 1.0  # seed
    assert out[-1].value > out[-2].value  # the jump pulls the EWMA up, but less than the raw 10
    assert out[-1].value < 10.0
    assert [p.available_at for p in out] == [p.available_at for p in pts]  # PIT: inherited, no look-ahead


def test_regime_is_binary_and_low_turnover_with_hysteresis_and_dwell():
    # a long quiet stretch, a sustained positive burst, back to quiet, a sustained negative burst
    vals = [0.0] * 30 + [0.6] * 40 + [0.0] * 30 + [-0.6] * 40
    accel = _accel_series(vals)
    reg = slow_social_regime(accel, ewma_days=20, min_dwell_days=20)
    assert reg, "regime should be defined once enough smoothed points exist"
    states = {p.value for p in reg}
    assert states <= {0.0, 1.0}  # binary {0,1} ∈ [0,1] by construction
    # turnover is LOW: a handful of flips, never a daily flip-flop
    flips = sum(1 for i in range(1, len(reg)) if reg[i].value != reg[i - 1].value)
    assert flips <= 4
    # availability is monotonic in ts (inherited from the smoothed accel) — no future leak
    avail = [p.available_at for p in reg]
    assert avail == sorted(avail)


def test_min_dwell_blocks_rapid_flip_flop():
    # alternating bursts FASTER than the dwell must be suppressed by the min-dwell hold
    vals = ([0.8] * 5 + [-0.8] * 5) * 12
    accel = _accel_series(vals)
    short_dwell = slow_social_regime(accel, ewma_days=5, min_dwell_days=2)
    long_dwell = slow_social_regime(accel, ewma_days=5, min_dwell_days=30)

    def _flips(r: list[AltDataPoint]) -> int:
        return sum(1 for i in range(1, len(r)) if r[i].value != r[i - 1].value)

    assert _flips(long_dwell) <= _flips(short_dwell)  # a longer dwell can only reduce turnover


# ---- (3) size-series mapping + dwell-preserving placebo --------------------------------------------


def test_size_series_maps_regime_to_tilt_bounds():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    regime = [
        AltDataPoint(ts=base, available_at=base, value=0.0),
        AltDataPoint(ts=base + timedelta(days=1), available_at=base + timedelta(days=1), value=1.0),
    ]
    one = Decimal("1")
    bars = [Bar(ts=base + timedelta(days=i), open=one, high=one, low=one, close=one, volume=one) for i in range(2)]
    ss = _size_series_from_regime(regime, bars)
    assert ss[bars[0].ts.isoformat()] == _TILT_LO          # risk-off ⇒ floor exposure
    assert ss[bars[1].ts.isoformat()] == _TILT_HI          # risk-on ⇒ full exposure


def test_time_shuffle_preserves_dwell_distribution():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    vals = [0.0] * 10 + [1.0] * 5 + [0.0] * 3 + [1.0] * 7
    regime = [AltDataPoint(ts=base + timedelta(days=i), available_at=base + timedelta(days=i), value=v)
              for i, v in enumerate(vals)]
    shuffled = _shuffle_regime_preserving_dwell(regime, seed=7)

    def _run_lengths(seq: list[float]) -> list[int]:
        out, cur, n = [], seq[0], 1
        for v in seq[1:]:
            if v == cur:
                n += 1
            else:
                out.append(n)
                cur, n = v, 1
        out.append(n)
        return sorted(out)

    orig = [p.value for p in regime]
    shuf = [p.value for p in shuffled]
    assert len(shuf) == len(orig)
    assert sum(shuf) == sum(orig)                       # same number of risk-on days (same on-fraction)
    assert _run_lengths(shuf) == _run_lengths(orig)     # IDENTICAL dwell-run-length distribution ⇒ same turnover
    # ts/availability are reattached to the original (sorted) order — PIT shape preserved
    assert [p.ts for p in shuffled] == [p.ts for p in regime]
