# intent: lock the HONEST maker execution lane — the per-venue MAKER fee resolvers (spine/asset_fees +
# screen_universe.build_maker_fee_schedule), the passive-fill realism (data/backtest.MakerFillModel: no-fill +
# adverse selection + queue, NO spread credit), and the invariant that TAKER (the default/floor) is byte-identical
# whether or not the maker machinery is wired. The maker lane exists to un-hide the reversion/fade/spread family
# (real at maker, dead at taker) WITHOUT becoming a free-spread-capture cheat.

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from cosmu.data.backtest import (
    DEFAULT_MAKER_FILL,
    MakerFillModel,
    _maker_entry_fill,
    _maker_touch_fills,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar
from cosmu.master.screen_universe import build_maker_fee_schedule
from cosmu.spine.asset_fees import (
    asset_maker_bps,
    asset_taker_bps,
    effective_maker_bps,
    polymarket_maker_bps,
)
from cosmu.spine.venue import Instrument, default_catalog
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)

# --------------------------------------------------------------------------- fixtures


def _wicky_up(n: int, *, step: str = "1.01", dip: str = "0.99") -> list[Bar]:
    """A steadily-rising series where EVERY bar prints a low BELOW its open (a `dip` wick) — so a passive long
    bid has a real adverse touch to fill against. Deterministic."""
    ts = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    price = Decimal("100")
    bars: list[Bar] = []
    for i in range(n):
        o = price
        c = (price * Decimal(step)).quantize(Decimal("0.0001"))
        low = (min(o, c) * Decimal(dip)).quantize(Decimal("0.0001"))
        bars.append(Bar(ts=ts + dt.timedelta(days=i), open=o, high=max(o, c), low=low, close=c, volume=Decimal("1000000")))
        price = c
    return bars


def _always_long(execution_mode: str = "taker", *, max_hold_days: int = 10_000) -> StrategySpec:
    """A long spec whose entry fires on essentially every bar (ret_Nd < a huge threshold) and which holds to the
    end (unreachable TP, very wide stop, huge time-stop) → exactly one trade per symbol. Used to compare maker vs
    taker COST on identical entries."""
    return StrategySpec(
        name="always-long",
        rationale="enter-and-hold cost probe; no edge if it loses to buy-and-hold net of fees on its own cell",
        disconfirmer="kill if net return ≤ buy-and-hold on its own cell",
        execution_mode=execution_mode,
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=max_hold_days),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="lookback")), op="lt", threshold=ParamRef(param="entry_thr"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="take")),
        risk=RiskRules(),
        param_space={
            "lookback": ParamSpace(kind="int", lo=2, hi=2),
            "entry_thr": ParamSpace(kind="float", lo=-1.0, hi=5.0),
            "stop": ParamSpace(kind="float", lo=0.01, hi=0.99),
            "take": ParamSpace(kind="float", lo=0.01, hi=10.0),
        },
    )


_PARAMS = {"lookback": 2, "entry_thr": 5.0, "stop": 0.99, "take": 10.0}  # fires always; TP/stop unreachable


# --------------------------------------------------------------------------- maker fee resolvers


def test_polymarket_maker_fee_is_a_zero_floor_never_a_rebate():
    """The Polymarket maker fee is a hard 0 at any price/category — the no-spread-credit floor. The rebate is
    NEVER credited (a negative bps would manufacture edge)."""
    assert polymarket_maker_bps("crypto", 0.5) == Decimal("0")
    assert polymarket_maker_bps("sports", 0.95) == Decimal("0")
    assert polymarket_maker_bps(None, 0.1) == Decimal("0")
    cat = default_catalog()
    poly = cat.venue("polymarket")
    inst = Instrument(id="m", venue_id="polymarket", symbol="X", asset_class="prediction", category="crypto")
    # maker (0) is strictly cheaper than the per-category taker (crypto 7% × (1−price) room) — never a rebate.
    assert asset_maker_bps(poly, inst, reference_price=0.5) == Decimal("0")
    assert asset_taker_bps(poly, inst, reference_price=0.5) > Decimal("0")


def test_ibkr_maker_equals_taker_commission():
    """IBKR's commission is per-share regardless of aggressor — there is no maker/taker split — so the maker bps
    equals the taker bps for an IBKR equity leg."""
    cat = default_catalog()
    ibkr = cat.venue("ibkr")
    inst = cat.instrument("SPY", "ibkr")
    assert asset_maker_bps(ibkr, inst, reference_price=500.0) == asset_taker_bps(ibkr, inst, reference_price=500.0)


def test_effective_maker_none_for_plain_crypto_venue():
    """A plain spot/perp venue (Binance) has no per-asset maker model → None, so the caller uses the venue's flat
    MAKER tier bps (Venue.effective_fee()[0])."""
    cat = default_catalog()
    binance = cat.venue("binance")
    inst = cat.instrument("BTCUSDT", "binance")
    assert effective_maker_bps(binance, inst, reference_price=50000.0) is None


def test_build_maker_fee_schedule_never_exceeds_taker():
    """The per-symbol maker fee schedule is ≤ the taker fee for every symbol (no rebate credited) — the honest
    maker saving is at most paying ZERO, never earning."""
    cat = default_catalog()
    spec = _always_long()
    market = {"BTCUSDT": _wicky_up(120)}
    maker = build_maker_fee_schedule(spec, market, cat)
    # Binance base maker == taker == 10 bps here; the invariant is maker ≤ taker, which must hold.
    assert maker["BTCUSDT"] <= cat.venue("binance").effective_fee()[1]


# --------------------------------------------------------------------------- passive-fill realism (unit)


def test_maker_entry_fill_no_spread_credit_long_and_short():
    """A maker fill is NEVER better than mid (the no-spread-credit floor): a long fills at ≥ open, a short at
    ≤ open. With a positive adverse-selection fraction the fill is strictly worse than mid."""
    bar = Bar(ts=dt.datetime(2024, 1, 1, tzinfo=dt.UTC), open=Decimal("100"), high=Decimal("101"),
              low=Decimal("98"), close=Decimal("100.5"), volume=Decimal("1000000"))
    model = MakerFillModel(fill_rate=1.0, adverse_selection_frac=0.5, queue_position_frac=1.0)
    base_slip = 0.0005  # 5 bps
    filled_long, px_long = _maker_entry_fill(100.0, +1, base_slip, bar, model, idx=10)
    filled_short, px_short = _maker_entry_fill(100.0, -1, base_slip, bar, model, idx=10)
    assert filled_long and px_long > 100.0      # long never fills below mid; adverse penalty pushes it ABOVE mid
    assert filled_short and px_short < 100.0     # short never fills above mid


def test_maker_entry_no_fill_when_market_never_touches():
    """A passive order only fills when the market moves AGAINST it: a long bid on a bar that never dips below open
    does NOT fill (no adverse touch) — the honest no-fill."""
    flat = Bar(ts=dt.datetime(2024, 1, 1, tzinfo=dt.UTC), open=Decimal("100"), high=Decimal("102"),
               low=Decimal("100"), close=Decimal("101"), volume=Decimal("1000000"))  # low == open, no dip
    model = MakerFillModel(fill_rate=1.0, adverse_selection_frac=0.5, queue_position_frac=1.0)
    filled, _ = _maker_entry_fill(100.0, +1, 0.0005, flat, model, idx=10)
    assert filled is False


def test_maker_touch_fills_is_deterministic_and_respects_fill_rate():
    bar = Bar(ts=dt.datetime(2024, 1, 1, tzinfo=dt.UTC), open=Decimal("100"), high=Decimal("101"),
              low=Decimal("99"), close=Decimal("100.5"), volume=Decimal("1000000"))
    assert _maker_touch_fills(bar, 5, 1.0) is True       # fill_rate 1 → always
    assert _maker_touch_fills(bar, 5, 0.0) is False       # fill_rate 0 → never
    # deterministic: the same (bar, idx) always returns the same draw
    assert _maker_touch_fills(bar, 5, 0.5) == _maker_touch_fills(bar, 5, 0.5)


# --------------------------------------------------------------------------- backtest integration


def test_taker_is_byte_identical_whether_or_not_maker_args_passed():
    """The conservative floor: a taker spec scores IDENTICALLY whether the maker fee/fill machinery is passed or
    not — maker args are ignored unless execution_mode == 'maker'."""
    spec = _always_long("taker")
    market = {"BTCUSDT": _wicky_up(160)}
    plain = run_strategy_backtest_detailed(spec, _PARAMS, market, fee_bps=Decimal("10"))
    with_maker = run_strategy_backtest_detailed(
        spec, _PARAMS, market, fee_bps=Decimal("10"),
        maker_fee_bps=Decimal("0"), maker_fill=MakerFillModel(fill_rate=0.1),
    )
    assert plain.metrics.oos_return == with_maker.metrics.oos_return
    assert plain.metrics.num_trades == with_maker.metrics.num_trades


def test_maker_zero_fill_rate_takes_no_trades():
    """fill_rate 0 → every passive order misses → ZERO trades (the extreme of the honest no-fill)."""
    spec = _always_long("maker")
    market = {"BTCUSDT": _wicky_up(160)}
    res = run_strategy_backtest_detailed(
        spec, _PARAMS, market, fee_bps=Decimal("10"), maker_fee_bps=Decimal("0"),
        maker_fill=MakerFillModel(fill_rate=0.0, adverse_selection_frac=0.5, queue_position_frac=1.0),
    )
    assert res.metrics.num_trades == 0


def test_maker_deep_queue_blocks_fills_the_bar_never_reaches():
    """A queue so deep that the required adverse move exceeds the bar's dip → no touch → no trades. The geometric
    no-fill/queue path (separate from the fill_rate draw)."""
    spec = _always_long("maker")
    market = {"BTCUSDT": _wicky_up(160, dip="0.999")}  # only a ~10 bps dip per bar
    res = run_strategy_backtest_detailed(
        spec, _PARAMS, market, fee_bps=Decimal("10"), maker_fee_bps=Decimal("0"),
        slippage_bps=Decimal("5"),
        # queue depth = 100 × 5 bps = 500 bps required adverse move; the bar only dips ~10 bps → never reached.
        maker_fill=MakerFillModel(fill_rate=1.0, adverse_selection_frac=0.5, queue_position_frac=100.0),
    )
    assert res.metrics.num_trades == 0


def test_maker_cheaper_fill_beats_taker_on_identical_single_trade():
    """Enter-and-hold (exactly one trade per cell, same entry bar in both modes). With a permissive fill model
    (always fills, no adverse penalty) and a 0-bps maker fee vs a 100-bps taker fee, the maker leg both fills at a
    BETTER price (mid vs mid+half-spread) and pays a LOWER fee → maker net return strictly beats taker. This is
    the honest reason the reversion/spread family is hidden by an always-taker engine."""
    market = {"BTCUSDT": _wicky_up(160)}
    taker = run_strategy_backtest_detailed(_always_long("taker"), _PARAMS, market, fee_bps=Decimal("100"))
    maker = run_strategy_backtest_detailed(
        _always_long("maker"), _PARAMS, market, fee_bps=Decimal("100"), maker_fee_bps=Decimal("0"),
        maker_fill=MakerFillModel(fill_rate=1.0, adverse_selection_frac=0.0, queue_position_frac=0.0),
    )
    assert taker.metrics.num_trades == maker.metrics.num_trades == 1
    assert maker.metrics.oos_return > taker.metrics.oos_return


def test_default_maker_fill_is_conservative():
    """The shipped default is the conservative floor the learning loop tightens — sane bands, no free lunch."""
    m = DEFAULT_MAKER_FILL
    assert 0.0 < m.fill_rate <= 1.0
    assert m.adverse_selection_frac >= 0.0   # never a spread CREDIT
    assert m.queue_position_frac >= 0.0
