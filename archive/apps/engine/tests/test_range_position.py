# The range_position (Donchian/stochastic channel position) bar-TA feature: locks the [0,1] math, the bounded /
# flat-channel guards, the registry↔route coherence, and that the range-floor accumulation spec that uses it
# validates + materializes the feature end-to-end. Offline, no store/network. Sibling of test_bb_width.py.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from cosmu.config.feature_registry import feature_names
from cosmu.data.backtest import _BAR_TA_FEATURES, PRICE_FEATURES, _feature_matrix, _range_position
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

_INBOX = Path(__file__).resolve().parents[1] / "strategies" / "inbox"
_RANGE_SPEC = _INBOX / "range-floor-accumulation-in-a-compressed-range-r.json"


def test_range_position_matches_donchian_formula_and_is_bounded():
    highs = [10, 11, 12, 11, 10, 9, 10, 11, 12, 13]
    lows = [9, 10, 11, 10, 9, 8, 9, 10, 11, 12]
    closes = [9.5, 10.5, 11.5, 10.5, 9.5, 8.5, 9.5, 10.5, 11.5, 12.5]
    lookback = 5
    out = _range_position(
        [float(h) for h in highs], [float(low) for low in lows], [float(c) for c in closes], lookback
    )
    assert out[:lookback] == [None] * lookback  # warmup: undefined until `lookback` bars exist
    for idx in range(lookback, len(closes)):
        window_high = max(highs[idx - lookback + 1 : idx + 1])
        window_low = min(lows[idx - lookback + 1 : idx + 1])
        expected = (closes[idx] - window_low) / (window_high - window_low)
        assert out[idx] == expected
    assert all(value is None or 0.0 <= value <= 1.0 for value in out)  # bounded [0,1]


def test_range_position_flat_channel_is_midpoint_not_a_div_error():
    # A zero-width channel (flat high==low) must not raise; it resolves to the midpoint 0.5.
    flat = [5.0] * 8
    assert _range_position(flat, flat, flat, 4)[-1] == 0.5


def test_range_position_is_registered_and_routed():
    assert "range_position" in _BAR_TA_FEATURES
    assert "range_position" in PRICE_FEATURES
    assert "range_position" in feature_names()  # enabled in the feature registry


def _bars(highs: list[float], lows: list[float], closes: list[float]) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for idx, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        bars.append(
            Bar(
                ts=ts + timedelta(hours=4 * idx),
                open=Decimal(str(close)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
                volume=Decimal("1000"),
            )
        )
    return bars


def test_range_floor_spec_validates_compiles_and_materializes_range_position():
    spec = StrategySpec.model_validate(json.loads(_RANGE_SPEC.read_text()))
    assert validate_spec(spec) == []  # no unknown features / no magic numbers
    params = fit_params(spec)
    compile_spec(spec, params)  # must not raise
    closes = [100.0 + (idx % 7) - 3 for idx in range(40)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    features = _feature_matrix(spec, params, _bars(highs, lows, closes))
    assert "range_position" in features
    assert any(value is not None for value in features["range_position"])
