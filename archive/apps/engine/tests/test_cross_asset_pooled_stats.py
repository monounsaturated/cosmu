# intent: pin the cross-asset pooled-statistics fixes so a mixed-calendar (equity + crypto/HL) spec is scored
# HONESTLY, not leniently. Two bugs were latent while only single-asset-class specs existed: (1) the cross-symbol
# correlation haircut on the PSR/DSR sample size aligned return streams POSITIONALLY (by index) — meaningless once
# equity (~252 sessions/yr) and crypto (365, 24/7) calendars are pooled, reading a spurious ≈0 that UNDER-deflates
# n_obs; (2) Sharpe annualized every symbol at 365, over-stating an equity leg by √(365/252) ≈ 1.2×. These tests
# assert the haircut now inner-joins on shared dates and annualization is asset-class-aware.

from __future__ import annotations

import datetime as dt
import math
import random
from decimal import Decimal

import pytest

from cosmu.data.backtest import (
    _MIN_CORR_OVERLAP,
    _avg_cross_correlation,
    _combine,
    _periods_per_year,
    _symbol_metrics,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.lab.finder import build_grid
from cosmu.spine.venue import default_catalog


# --------------------------------------------------------------------- annualization is asset-class-aware (bug 2)


def test_periods_per_year_is_asset_class_aware():
    # Daily bars: crypto/HL/prediction trade 24/7 (365 sessions), equities/FX a ~252-session weekday year.
    assert _periods_per_year("1d", "crypto") == 365.0
    assert _periods_per_year("1d", "prediction") == 365.0
    assert _periods_per_year("1d", "equity") == 252.0
    assert _periods_per_year("1d", "fx") == 252.0
    # Unknown / unlabelled symbols fall back to the 365 crypto default → single-asset crypto stays byte-identical.
    assert _periods_per_year("1d", None) == 365.0
    assert _periods_per_year("1d", "mystery") == 365.0
    # The bars/session factor scales both classes equally, so the equity:crypto ratio is always √(252/365).
    assert _periods_per_year("1h", "equity") == 252.0 * 24.0
    assert _periods_per_year("4h", "crypto") == 365.0 * 6.0
    assert _periods_per_year("1h", "equity") / _periods_per_year("1h", "crypto") == pytest.approx(252.0 / 365.0)


def test_combine_bar_weights_annualization_across_calendars():
    # Two synthetic per-symbol runs on different calendars: 40 equity bars @252, 80 crypto bars @365.
    eq_equity = [100000.0 * (1.0 + 0.001) ** i for i in range(41)]
    cr_equity = [100000.0 * (1.0 + 0.002) ** i for i in range(81)]
    eq = _symbol_metrics(eq_equity, [], periods_per_year=252.0, equity_ts=[f"e{i}" for i in range(41)])
    cr = _symbol_metrics(cr_equity, [], periods_per_year=365.0, equity_ts=[f"c{i}" for i in range(81)])
    assert eq.periods_per_year == 252.0
    assert cr.periods_per_year == 365.0
    # bar_ts is carried parallel to bar_returns (the keystone for the calendar-aware haircut).
    assert len(eq.bar_ts) == len(eq.bar_returns) == 40
    assert len(cr.bar_ts) == len(cr.bar_returns) == 80

    combined = _combine([eq, cr])
    # Bar-count-weighted blend: 40 equity bars + 80 crypto bars → strictly between 252 and 365, never a flat 365.
    assert combined.periods_per_year == pytest.approx((40 * 252.0 + 80 * 365.0) / 120)
    assert 252.0 < combined.periods_per_year < 365.0
    assert len(combined.bar_ts) == len(combined.bar_returns) == 120
    # A same-calendar pool is unchanged: an all-crypto book still annualizes at exactly 365 (no silent drift).
    assert _combine([cr, cr]).periods_per_year == 365.0


# --------------------------------------------------------------------- the haircut joins on calendar, not position (bug 1)


def test_cross_correlation_joins_on_calendar_not_position():
    # A crypto stream prints every UTC day; an equity stream prints only weekdays, with the SAME return on the
    # days it trades. The two are perfectly correlated on the dates they SHARE — but their indices don't line up.
    rng = random.Random(11)
    base = dt.datetime(2023, 1, 2, tzinfo=dt.UTC)  # a Monday
    crypto_ret: list[float] = []
    crypto_ts: list[str] = []
    eq_ret: list[float] = []
    eq_ts: list[str] = []
    for d in range(120):
        day = base + dt.timedelta(days=d)
        r = rng.gauss(0.0, 0.01)
        crypto_ret.append(r)
        crypto_ts.append(day.isoformat())
        if day.weekday() < 5:  # equity trades weekdays only — identical return on the days it DOES trade
            eq_ret.append(r)
            eq_ts.append(day.isoformat())

    # Calendar-aware inner join over the shared weekdays (well above _MIN_CORR_OVERLAP) → identical → ρ = 1.0.
    joined = _avg_cross_correlation([crypto_ret, eq_ret], [crypto_ts, eq_ts])
    assert joined == pytest.approx(1.0, abs=1e-9)
    # Legacy positional alignment tail-trims the 120-day crypto stream onto the ~86-pt equity stream and pairs by
    # INDEX across mismatched calendars → a spurious near-zero that under-deflates n_obs (the bug this replaces).
    positional = _avg_cross_correlation([crypto_ret, eq_ret])
    assert abs(positional) < 0.4
    assert joined > positional + 0.5


def test_cross_correlation_drops_thin_calendar_overlap():
    # Two streams whose calendars barely overlap share too few dates to estimate correlation honestly.
    rng = random.Random(3)
    base = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)
    a = [rng.gauss(0.0, 0.01) for _ in range(50)]
    b = [rng.gauss(0.0, 0.01) for _ in range(50)]
    a_ts = [(base + dt.timedelta(days=i)).isoformat() for i in range(50)]
    overlap = _MIN_CORR_OVERLAP - 5  # fewer than the minimum shared bars
    b_ts = [(base + dt.timedelta(days=i)).isoformat() for i in range(50 - overlap, 100 - overlap)]
    # The only pair shares < _MIN_CORR_OVERLAP timestamps → dropped → no usable correlation → 0.0 (not fabricated).
    assert _avg_cross_correlation([a, b], [a_ts, b_ts]) == 0.0


def test_avg_cross_correlation_falls_back_to_positional_without_timestamps():
    # Bare-stream callers (and same-calendar crypto cohorts) keep the legacy common-tail behaviour exactly.
    a = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01]
    assert _avg_cross_correlation([a, a]) == pytest.approx(1.0, abs=1e-9)
    assert _avg_cross_correlation([a]) == 0.0


# --------------------------------------------------------------------- end-to-end: a pooled equity+crypto backtest


def _trending_bars(n: int = 300, seed: int = 5) -> list[Bar]:
    """A deterministic trending-with-pullbacks hourly series that the ORB+FVG seed actually trades on."""
    rng = random.Random(seed)
    base = dt.datetime(2022, 1, 1, tzinfo=dt.UTC)
    price = 100.0
    bars: list[Bar] = []
    for i in range(n):
        r = 0.004 + 0.02 * math.sin(i / 9.0) + rng.gauss(0.0, 0.01)
        o = price
        price = max(1e-6, price * (1 + r))
        hi = max(o, price) * (1 + abs(rng.gauss(0.0, 0.004)))
        lo = min(o, price) * (1 - abs(rng.gauss(0.0, 0.004)))
        bars.append(Bar(ts=base + dt.timedelta(hours=i), open=Decimal(str(o)), high=Decimal(str(hi)),
                        low=Decimal(str(lo)), close=Decimal(str(price)), volume=Decimal("1000")))
    return bars


def test_pooled_backtest_annualizes_each_leg_on_its_own_calendar_and_haircuts():
    """The integration guard: pool an equity-calendar leg with a crypto leg through the real backtest and assert
    BOTH pooled-stats fixes fire — the equity leg annualizes at 252 (not 365) and the correlation haircut deflates
    the pooled observation count."""
    spec = seed_orb_fvg_spec()
    params = build_grid(spec, max_variants=1)[0].params
    fee = default_catalog().venue("binance").taker_fee_bps
    bars = _trending_bars()
    # Score the SAME bars as an equity symbol AND a crypto symbol. Identical bars ⇒ identical trades ⇒ identical
    # per-observation Sharpe, so the ONLY thing that can differ between the two legs is the annualization calendar.
    market = {"SPY": bars, "BTCUSDT": bars}
    res = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=fee,
        asset_class_by_symbol={"SPY": "equity", "BTCUSDT": "crypto"},
    )
    assert res.metrics.num_trades > 0  # the seed actually trades this series (else the ratio is undefined)

    sp = res.per_symbol["SPY"]["sharpe"]
    bt = res.per_symbol["BTCUSDT"]["sharpe"]
    assert bt != 0.0
    # bug 2 fixed: equity annualizes at 252, crypto at 365 → equity/crypto Sharpe = √(252/365), exactly.
    assert sp / bt == pytest.approx(math.sqrt(252.0 / 365.0), rel=1e-4)

    # bug 1 fixed: the two perfectly-correlated legs are NOT 2× the independent observations — the calendar-aware
    # haircut (here identical calendars → ρ = 1.0) halves the pooled count instead of leaving it un-deflated.
    pooled = len(res.val_returns)
    assert res.metrics.n_obs < pooled
    assert res.metrics.n_obs == pytest.approx(pooled / 2, abs=2)


def test_crypto_only_pool_is_unchanged_by_the_calendar_fix():
    """A single-asset crypto pool (no asset_class map) must be byte-identical to leaving the argument unset — the
    fix is dormant until a spec genuinely mixes calendars."""
    spec = seed_orb_fvg_spec()
    params = build_grid(spec, max_variants=1)[0].params
    fee = default_catalog().venue("binance").taker_fee_bps
    market = {"BTCUSDT": _trending_bars(seed=1), "ETHUSDT": _trending_bars(seed=2)}
    baseline = run_strategy_backtest_detailed(spec, params, market, fee_bps=fee)
    crypto_tagged = run_strategy_backtest_detailed(
        spec, params, market, fee_bps=fee,
        asset_class_by_symbol={"BTCUSDT": "crypto", "ETHUSDT": "crypto"},
    )
    assert crypto_tagged.metrics.sharpe == baseline.metrics.sharpe
    assert crypto_tagged.metrics.n_obs == baseline.metrics.n_obs
    assert crypto_tagged.metrics.sharpe_per_obs == baseline.metrics.sharpe_per_obs
