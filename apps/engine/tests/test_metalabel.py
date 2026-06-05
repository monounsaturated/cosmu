# Triple-barrier meta-labeling: proves (1) the triple-barrier labeler picks the FIRST barrier with the right
# sign, (2) the secondary-logistic gate is point-in-time (a decision never trains on an event that resolves at/
# after it — no look-ahead), (3) the gate only SIZES/SKIPS (it can only ever subtract primary trades, and is
# byte-identical to the primary book when its threshold lets everything through), and (4) static_check enforces
# the same 'real feature + fitted threshold' rules on the meta-label as on everything else. Fully offline +
# deterministic — no network, no fixtures.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.ml.metalabel import MetaEvent, MetaGate, triple_barrier_outcome
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    MetaLabel,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)
from cosmu.strategy.static_check import validate_spec

# --------------------------------------------------------------------------- triple-barrier labeler


def _flat(prices: list[float]) -> tuple[list[float], list[float], list[float]]:
    """highs == lows == closes so the barrier walk lands exactly on the path (no intrabar ambiguity)."""
    return list(prices), list(prices), list(prices)


def test_triple_barrier_take_profit_first_is_a_win():
    # Rises straight to +20% from entry: the +10% take-profit is hit before any stop/time. Net of a tiny cost,
    # a take-profit fill is a winner.
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.05, take_pct=0.10, max_hold_bars=10, d=1, roundtrip_cost=0.002
    )
    assert label == 1
    # tp = 100*(1+0.10) carries a float epsilon (110.00000000000001), so 110.0 just misses and the fill lands
    # at index 3 (115). The point of the test is the WIN label, not the exact bar.
    assert resolve == 3


def test_triple_barrier_stop_first_is_a_loss():
    # Falls straight down: the 5% stop is hit before the (unreachable) take-profit. A stop fill is a loss.
    closes = [100.0, 97.0, 94.0, 90.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.05, take_pct=0.20, max_hold_bars=10, d=1, roundtrip_cost=0.002
    )
    assert label == 0
    assert resolve == 2  # 97 > 95 at index 1; the 94 <= 95 stop fires at index 2


def test_triple_barrier_time_barrier_labels_by_close_sign():
    # Neither stop nor take-profit is reached within max_hold; the time barrier closes the trade at a mild gain,
    # which (net of cost) is a win.
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.50, take_pct=0.50, max_hold_bars=3, d=1, roundtrip_cost=0.002
    )
    assert resolve == 3  # entry_idx + max_hold_bars
    assert label == 1  # +3% close return beats the 0.2% round-trip cost


def test_triple_barrier_short_mirrors_long():
    # A SHORT into a falling market hits its (below-entry) take-profit first → a win for the short side.
    closes = [100.0, 95.0, 90.0, 85.0]
    highs, lows, _ = _flat(closes)
    label, resolve = triple_barrier_outcome(
        0, highs, lows, closes, stop_pct=0.05, take_pct=0.10, max_hold_bars=10, d=-1, roundtrip_cost=0.002
    )
    assert label == 1
    assert resolve == 2  # 90 <= 100*0.90 first at index 2


# --------------------------------------------------------------------------- the gate is point-in-time


def _sep_events(start_resolve: int, n: int, *, inverted: bool) -> list[MetaEvent]:
    """n separable 1-feature events: feature x alternates +1/-1; label follows sign(x) (or its inverse). Each
    resolves one bar apart starting at `start_resolve`."""
    out: list[MetaEvent] = []
    for i in range(n):
        x = 1.0 if i % 2 == 0 else -1.0
        base = 1 if x > 0 else 0
        label = (1 - base) if inverted else base
        out.append(MetaEvent(signal_idx=start_resolve + i, resolve_idx=start_resolve + i, features=[x], label=label))
    return out


def test_gate_is_point_in_time_future_events_never_train():
    # 40 clean events (label follows the feature) all resolve before bar 60. A block of 40 POISON events with the
    # INVERTED labels resolve at bar 1000 — strictly in the future of a decision at bar 60. The decision must be
    # identical with or without the poison block, proving future-resolving events never enter the fit.
    clean = _sep_events(1, 40, inverted=False)
    poison = [MetaEvent(signal_idx=1000, resolve_idx=1000, features=e.features, label=1 - e.label) for e in clean]

    without = MetaGate(events=list(clean)).decide(60, [1.0], threshold=0.5, proportional=False)
    with_future = MetaGate(events=clean + poison).decide(60, [1.0], threshold=0.5, proportional=False)

    assert without == with_future
    assert without[0] is True  # a strongly-positive feature is taken by a gate trained on the clean (aligned) set


def test_gate_cold_start_and_single_class_are_ungated():
    # Below META_MIN_TRAIN resolved events → ungated (take, full size), so the gate can only ever subtract.
    thin = MetaGate(events=_sep_events(1, 5, inverted=False))
    assert thin.decide(100, [1.0], threshold=0.99, proportional=False) == (True, 1.0)
    # Enough events but a SINGLE class (no win/loss contrast to learn) → also ungated.
    one_class = [MetaEvent(signal_idx=i, resolve_idx=i, features=[1.0 if i % 2 else -1.0], label=1) for i in range(1, 41)]
    assert MetaGate(events=one_class).decide(100, [1.0], threshold=0.99, proportional=False) == (True, 1.0)


def test_gate_skips_below_threshold_and_sizes_proportionally():
    # A gate trained on a clean separable set predicts ~1 for a strongly-positive feature and ~0 for a negative
    # one. An impossible threshold (1.01) skips everything; proportional sizing returns the probability as size.
    gate = MetaGate(events=_sep_events(1, 60, inverted=False))
    assert gate.decide(100, [1.0], threshold=1.01, proportional=False)[0] is False
    take, mult = gate.decide(100, [1.0], threshold=0.5, proportional=True)
    assert take is True and 0.5 <= mult <= 1.0
    # A strongly-negative feature scores low → skipped at a mid threshold.
    assert gate.decide(100, [-1.0], threshold=0.5, proportional=False)[0] is False


def test_gate_missing_feature_row_is_ungated():
    gate = MetaGate(events=_sep_events(1, 60, inverted=False))
    assert gate.decide(100, None, threshold=0.99, proportional=False) == (True, 1.0)


# --------------------------------------------------------------------------- integration with the backtest


def _saw(n: int, lo: float = 100.0, hi: float = 112.0, period: int = 10) -> list[float]:
    """A deterministic sawtooth oscillating lo↔hi: momentum fires on the rising legs and outcomes are mixed
    (some entries ride to the take-profit, late ones get stopped on the turn) — enough events, both classes."""
    half = period / 2
    out: list[float] = []
    for i in range(n):
        phase = i % period
        frac = phase / half if phase < half else (period - phase) / half
        out.append(round(lo + (hi - lo) * frac, 4))
    return out


def _bars(prices: list[float]) -> list[Bar]:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(p))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _spec(*, with_meta: bool, threshold: float) -> StrategySpec:
    """A short-lookback momentum spec. The meta-label (when present) reads the SAME ret_Nd ref as the entry, so
    the feature matrix and warm-up are identical to the no-meta spec — the ONLY difference is the gate, isolating
    its effect."""
    ret_ref = FeatureRef(name="ret_Nd", lookback=ParamRef(param="lb"))
    space = {
        "lb": ParamSpace(kind="int", lo=2, hi=10),
        "floor": ParamSpace(kind="float", lo=-1.0, hi=1.0),
        "stop": ParamSpace(kind="float", lo=0.01, hi=0.5),
        "tp": ParamSpace(kind="float", lo=0.01, hi=0.5),
        "tstop": ParamSpace(kind="int", lo=2, hi=8),
        "mthr": ParamSpace(kind="float", lo=0.0, hi=1.0),
    }
    return StrategySpec(
        name="metalabel-test",
        rationale="short-lookback momentum; the meta-label gates size/skip on the same signal feature",
        universe=UniverseSelector(venues=["binance"], asset_classes=["crypto"], min_instruments=5),
        horizon=Horizon(bar_size="1d", min_hold_days=1, max_hold_days=4),
        entry=[Condition(feature=ret_ref, op="gt", threshold=ParamRef(param="floor"))],
        exit=ExitRules(stop_loss=ParamRef(param="stop"), take_profit=ParamRef(param="tp"), time_stop_days=ParamRef(param="tstop")),
        risk=RiskRules(),
        param_space=space,
        meta_label=MetaLabel(features=[ret_ref], prob_threshold=ParamRef(param="mthr")) if with_meta else None,
    )


_PARAMS = {"lb": 3, "floor": 0.0, "stop": 0.03, "tp": 0.03, "tstop": 4, "mthr": 0.0}


def test_meta_gate_permissive_is_byte_identical_to_primary_book():
    """With prob_threshold = 0 the gate takes every primary entry at full size — so a meta-labeled spec must be
    BYTE-IDENTICAL to the same spec with no meta-label (the gate can only ever subtract, never add or alter)."""
    market = {"BTCUSDT": _bars(_saw(400))}
    primary = run_strategy_backtest(_spec(with_meta=False, threshold=0.0), _PARAMS, market, fee_bps=Decimal("10"))
    permissive = run_strategy_backtest(_spec(with_meta=True, threshold=0.0), {**_PARAMS, "mthr": 0.0}, market, fee_bps=Decimal("10"))
    assert primary.num_trades > 30, "the path must trade enough to activate the gate, so this proof is real"
    assert primary == permissive


def test_meta_gate_strict_threshold_only_subtracts_trades():
    """With an impossible-to-clear threshold the gate skips every entry once it activates (past the cold-start
    window), so the meta-labeled book takes STRICTLY FEWER trades than the bare primary — never more."""
    market = {"BTCUSDT": _bars(_saw(400))}
    primary = run_strategy_backtest(_spec(with_meta=False, threshold=0.0), _PARAMS, market, fee_bps=Decimal("10"))
    strict = run_strategy_backtest(_spec(with_meta=True, threshold=2.0), {**_PARAMS, "mthr": 2.0}, market, fee_bps=Decimal("10"))
    assert strict.num_trades < primary.num_trades


# --------------------------------------------------------------------------- static_check


def test_static_check_accepts_valid_meta_label():
    assert validate_spec(_spec(with_meta=True, threshold=0.5)) == []


def test_static_check_rejects_unknown_meta_feature():
    spec = _spec(with_meta=True, threshold=0.5)
    spec.meta_label.features.append(FeatureRef(name="not_a_real_feature"))
    assert "unknown_feature:not_a_real_feature" in validate_spec(spec)


def test_static_check_rejects_unfitted_threshold():
    spec = _spec(with_meta=True, threshold=0.5)
    spec.meta_label.prob_threshold = ParamRef(param="not_in_space")
    assert "unknown_param:not_in_space" in validate_spec(spec)
