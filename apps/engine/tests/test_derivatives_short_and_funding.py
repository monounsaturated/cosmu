# Phase-0 derivatives foundation (P0.1 + P0.2): proves the short side and funding accrual are correct and,
# critically, that the existing spot/long path is BYTE-IDENTICAL when the new derivatives knobs are at their
# defaults (direction=+1, funding_feature=None). Fully offline + deterministic — no network, no fixtures.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.core import Instrument, Order, Position, ProductType
from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
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
from cosmu.strategy.static_check import validate_spec


def _bars(prices: list[float]) -> list[Bar]:
    """Flat OHLC bars at the given closes (open=high=low=close) so fills land exactly on the path — no
    intrabar ambiguity. Volume is large so capacity slippage stays negligible."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(p))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _ts_keys(bars: list[Bar]) -> list[str]:
    return [b.ts.isoformat() for b in bars]


def _spec(direction: int = 1, funding_feature: str | None = None) -> StrategySpec:
    """A simple ret_Nd-momentum spec. Entry conditions are direction-agnostic; `direction` only flips which
    way the resulting position is taken (long vs short)."""
    return StrategySpec(
        name="deriv-test",
        rationale="momentum entry; direction flips the position side; funding accrues on the perp leg",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=60),
        entry=[Condition(feature=FeatureRef(name="ret_Nd", lookback=ParamRef(param="lb")), op="gt", threshold=ParamRef(param="floor"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp")),
        risk=RiskRules(),
        param_space={
            "lb": ParamSpace(kind="int", lo=2, hi=20),
            "floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
            "stop": ParamSpace(kind="float", lo=0.01, hi=0.5),
            "tp": ParamSpace(kind="float", lo=0.01, hi=0.5),
        },
        direction=direction,
        funding_feature=funding_feature,
    )


_PARAMS = {"lb": 5, "floor": -0.5, "stop": 0.5, "tp": 0.5}  # wide stop/tp so the time-stop exits the trade


def _ramp(start: float, per_bar: float, n: int) -> list[float]:
    """A deterministic geometric price path of n bars compounding `per_bar` each step (negative => decline).
    The backtest needs >= 80 bars per symbol, so all paths here are long enough to actually trade."""
    out = [start]
    for _ in range(n - 1):
        out.append(round(out[-1] * (1 + per_bar), 6))
    return out


# ---------- data model: spot defaults stay backward-compatible ----------------------------------------------


def test_data_model_spot_defaults_unchanged():
    inst = Instrument(
        id="binance:BTCUSDT", symbol="BTCUSDT", asset_class="crypto", venue="binance",
        tick_size=Decimal("0.01"), lot_size=Decimal("0.001"), min_notional=Decimal("10"), quote_ccy="USDT",
    )
    assert inst.product_type is ProductType.SPOT
    assert inst.is_inverse is False
    assert inst.funding is None
    assert inst.max_leverage == 1
    assert inst.maintenance_margin_pct == Decimal("0")
    assert inst.expiry_ts is None

    order = Order(
        instrument_id="binance:BTCUSDT", side=1, qty=Decimal("1"), order_type="market",
        limit_price=None, client_order_id="x", ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert order.leverage == 1
    assert order.reduce_only is False

    pos = Position(instrument_id="binance:BTCUSDT", qty=Decimal("1"), avg_price=Decimal("100"), ts=datetime(2026, 1, 1, tzinfo=UTC))
    assert pos.liquidation_price is None
    assert pos.funding_accrued == Decimal("0")


def test_position_qty_is_signed_for_shorts():
    short = Position(instrument_id="x", qty=Decimal("-2"), avg_price=Decimal("100"), ts=datetime(2026, 1, 1, tzinfo=UTC))
    assert short.qty < 0  # the signed-qty short convention


def test_perp_instrument_carries_derivative_fields():
    perp = Instrument(
        id="okx:BTC-USDT-SWAP", symbol="BTC-USDT-SWAP", asset_class="crypto", venue="okx",
        tick_size=Decimal("0.1"), lot_size=Decimal("0.001"), min_notional=Decimal("10"), quote_ccy="USDT",
        product_type=ProductType.PERP, funding=Decimal("0.0001"), max_leverage=2,
        maintenance_margin_pct=Decimal("0.005"),
    )
    assert perp.product_type is ProductType.PERP
    assert perp.funding == Decimal("0.0001")
    assert perp.max_leverage == 2


def test_short_spec_passes_static_check():
    assert validate_spec(_spec(direction=-1, funding_feature="funding_rate")) == []


# ---------- the spot path is unchanged by the new machinery -------------------------------------------------


# A path that climbs for the warmup then declines for the rest: entries arm (ret_Nd>floor stays satisfiable)
# and the held position rides the decline — so a long loses and the mirror short profits.
_DECLINE = _ramp(100.0, 0.02, 12) + _ramp(_ramp(100.0, 0.02, 12)[-1], -0.01, 108)
# A rising-then-flat path: the held long is profitable; used for the spot-unchanged / zero-funding no-ops.
_RISE = _ramp(100.0, 0.01, 120)


def test_spot_path_unchanged_when_funding_feature_none():
    """A plain long spec (no direction, no funding_feature) and an explicit direction=+1 spec must produce the
    EXACT same metrics — the new fields default to spot semantics."""
    market = {"BTCUSDT": _bars(_RISE)}
    base = run_strategy_backtest(_spec(), _PARAMS, market, fee_bps=Decimal("10"))
    explicit_long = run_strategy_backtest(_spec(direction=1), _PARAMS, market, fee_bps=Decimal("10"))
    assert base.num_trades > 0  # the path actually trades, so this is a real proof
    assert base == explicit_long


def test_zero_funding_is_a_no_op_for_a_long():
    """Supplying a funding_feature whose rate is identically zero must not move a single number — funding only
    bites when the rate is non-zero, so the spot/long curve is preserved."""
    bars = _bars(_RISE)
    market = {"BTCUSDT": bars}
    no_funding = run_strategy_backtest(_spec(), _PARAMS, market, fee_bps=Decimal("10"))
    zero_alt = {"BTCUSDT": {"funding_rate": {k: 0.0 for k in _ts_keys(bars)}}}
    with_zero = run_strategy_backtest(
        _spec(funding_feature="funding_rate"), _PARAMS, market, fee_bps=Decimal("10"), alt_by_symbol=zero_alt
    )
    assert no_funding.num_trades > 0
    assert no_funding == with_zero


# ---------- the short side is correct -----------------------------------------------------------------------


def test_short_profits_when_price_falls():
    """On a steadily FALLING path after entry, a short makes money and the mirror long loses it."""
    market = {"BTCUSDT": _bars(_DECLINE)}
    long = run_strategy_backtest(_spec(direction=1), _PARAMS, market, fee_bps=Decimal("10"))
    short = run_strategy_backtest(_spec(direction=-1), _PARAMS, market, fee_bps=Decimal("10"))
    assert long.num_trades > 0 and short.num_trades > 0
    assert short.oos_return > 0, "a short into a falling market should be profitable"
    assert long.oos_return < 0, "the mirror long into the same fall should lose"


# ---------- funding accrues with the correct sign -----------------------------------------------------------


def _funding_alt(bars: list[Bar], rate: float) -> dict:
    return {"BTCUSDT": {"funding_rate": {k: rate for k in _ts_keys(bars)}}}


def test_funding_sign_long_pays_short_receives_on_positive_rate():
    """With a POSITIVE funding rate held flat: a long PAYS funding (return drops vs zero funding), a short
    RECEIVES it (return rises vs zero funding). This is the carry P&L sign that the whole thesis rests on."""
    bars = _bars(_RISE)  # mild upward drift so trades open and hold; funding effect is isolated by the diff
    market = {"BTCUSDT": bars}
    pos_rate = _funding_alt(bars, 0.01)  # large, held-flat positive funding so the effect dominates

    long_zero = run_strategy_backtest(_spec(direction=1, funding_feature="funding_rate"), _PARAMS, market, fee_bps=Decimal("10"), alt_by_symbol=_funding_alt(bars, 0.0))
    long_pos = run_strategy_backtest(_spec(direction=1, funding_feature="funding_rate"), _PARAMS, market, fee_bps=Decimal("10"), alt_by_symbol=pos_rate)
    short_zero = run_strategy_backtest(_spec(direction=-1, funding_feature="funding_rate"), _PARAMS, market, fee_bps=Decimal("10"), alt_by_symbol=_funding_alt(bars, 0.0))
    short_pos = run_strategy_backtest(_spec(direction=-1, funding_feature="funding_rate"), _PARAMS, market, fee_bps=Decimal("10"), alt_by_symbol=pos_rate)

    assert long_pos.num_trades > 0 and short_pos.num_trades > 0
    assert long_pos.oos_return < long_zero.oos_return, "a long perp PAYS positive funding"
    assert short_pos.oos_return > short_zero.oos_return, "a short perp RECEIVES positive funding"
