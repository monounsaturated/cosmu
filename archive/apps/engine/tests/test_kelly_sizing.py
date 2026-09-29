# T2 fractional-Kelly self-sizing (master/sizing.kelly_size_multiplier). The multiplier is derived from the Gate's
# DEFLATED edge and applied as a FROZEN funding-time scalar ON TOP of size_fraction — never threaded inside it, so
# the backtest==forward==live parity asserted in test_sizing.py is untouched. These tests pin the contract.
from __future__ import annotations

from cosmu.master.sizing import _KELLY_FLOOR, _KELLY_SCALE, kelly_size_multiplier


def test_max_confidence_deploys_half_kelly():
    # deflated_edge → 1.0 ⇒ the cell deploys the full fractional-Kelly scale (half-Kelly by default).
    assert kelly_size_multiplier(1.0) == _KELLY_SCALE


def test_monotone_nondecreasing_in_edge():
    edges = [0.0, 0.2, 0.5, 0.8, 0.95, 1.0]
    vals = [kelly_size_multiplier(e) for e in edges]
    assert vals == sorted(vals), "Kelly multiplier must be monotone non-decreasing in the deflated edge"


def test_floor_binds_for_weak_edge():
    # A near-zero deflated edge is floored (a passed cell still deploys a scoreable stream), never 0.
    assert kelly_size_multiplier(0.0) == _KELLY_FLOOR
    assert kelly_size_multiplier(0.01) == _KELLY_FLOOR


def test_output_bounded_in_floor_scale():
    for e in [0.0, 0.3, 0.6, 0.91, 0.96, 1.0]:
        m = kelly_size_multiplier(e)
        assert _KELLY_FLOOR <= m <= _KELLY_SCALE


def test_input_clamped_to_unit_interval():
    # The input is a PROBABILITY in [0,1]; a caller that passes a raw Sharpe (>1) or a negative degrades safely.
    assert kelly_size_multiplier(5.0) == _KELLY_SCALE       # clamped to 1.0 → full scale
    assert kelly_size_multiplier(-1.0) == _KELLY_FLOOR      # clamped to 0.0 → floor


def test_passed_grade_edge_is_near_half_kelly():
    # Gate DSR bar is 0.95; a passed cell deploys ~half-Kelly (high-confidence ⇒ near the full scale), strictly
    # below the max so a 1.0-confidence cell still ranks above a 0.95 one.
    m95 = kelly_size_multiplier(0.95)
    assert 0.45 <= m95 < _KELLY_SCALE
    assert kelly_size_multiplier(0.99) > m95


def test_pure_and_deterministic():
    assert kelly_size_multiplier(0.96) == kelly_size_multiplier(0.96)


def test_custom_scale_overrides_default():
    # Quarter-Kelly: a more conservative caller can pass a tighter scale (sizing constants are never param_space).
    assert kelly_size_multiplier(1.0, kelly_scale=0.25) == 0.25
    # Floor still binds under a custom scale.
    assert kelly_size_multiplier(0.0, kelly_scale=0.25, floor=0.05) == 0.05
