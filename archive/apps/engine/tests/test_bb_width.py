# The bb_width (Bollinger Bandwidth) bar-TA feature: locks the textbook 4·σ/mean math, the registry↔route
# coherence (enabled feature must be bar-computed, not dead), and that the squeeze-release reversion spec that
# uses it validates + materializes the feature end-to-end. Offline, no store/network.

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from cosmu.config.feature_registry import feature_names
from cosmu.data.backtest import _BAR_TA_FEATURES, PRICE_FEATURES, _bb_width, _feature_matrix
from cosmu.data.market import Bar
from cosmu.evolution.loop import fit_params
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

_INBOX = Path(__file__).resolve().parents[1] / "strategies" / "inbox"
_SQUEEZE_SPEC = _INBOX / "bollinger-squeeze-release-reversion-regime-break.json"


def test_bb_width_matches_textbook_bandwidth():
    # (upper - lower) / basis with ±2σ bands == 4·σ / mean over the SAME rolling window as bb_z.
    vals = [10, 11, 12, 11, 10, 9, 10, 11, 12, 13, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13]
    lookback = 5
    out = _bb_width([float(v) for v in vals], lookback)
    assert out[:lookback] == [None] * lookback  # warmup: undefined until `lookback` bars exist
    for idx in range(lookback, len(vals)):
        window = vals[idx - lookback + 1 : idx + 1]
        expected = 4.0 * statistics.pstdev(window) / statistics.fmean(window)
        assert out[idx] == expected


def test_bb_width_flat_basis_is_zero_not_a_div_error():
    # A perfectly flat window has zero σ → zero width, and a zero mean must not raise (guarded → 0.0).
    assert _bb_width([5.0] * 10, 4)[-1] == 0.0
    assert _bb_width([0.0] * 10, 4)[-1] == 0.0


def test_bb_width_is_registered_and_routed():
    # The registry↔route guard: an ENABLED feature must be bar-computed (in PRICE_FEATURES) or store-routed.
    assert "bb_width" in _BAR_TA_FEATURES
    assert "bb_width" in PRICE_FEATURES
    assert "bb_width" in feature_names()  # enabled in the feature registry


def _bars(closes: list[float]) -> list[Bar]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[Bar] = []
    for idx, close in enumerate(closes):
        c = Decimal(str(close))
        bars.append(
            Bar(
                ts=ts + timedelta(hours=4 * idx),
                open=c,
                high=(c * Decimal("1.01")),
                low=(c * Decimal("0.99")),
                close=c,
                volume=Decimal("1000"),
            )
        )
    return bars


def test_squeeze_spec_validates_compiles_and_materializes_bb_width():
    spec = StrategySpec.model_validate(json.loads(_SQUEEZE_SPEC.read_text()))
    assert validate_spec(spec) == []  # no unknown features / no magic numbers
    params = fit_params(spec)
    compile_spec(spec, params)  # must not raise
    closes = [100.0 + (idx % 7) - 3 for idx in range(40)]  # a low-amplitude wiggle so the window has spread
    features = _feature_matrix(spec, params, _bars(closes))
    assert "bb_width" in features  # the entry condition's feature was actually computed
    assert any(value is not None for value in features["bb_width"])  # populated past the warmup
