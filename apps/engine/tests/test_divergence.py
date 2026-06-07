# The SIM-vs-backtest divergence signal (master/divergence.py): an early warning that a funded track's REAL
# marked forward return has stopped tracking the backtest it was funded on. These tests pin ONLY the pure
# arithmetic + the fail-safe behaviour. Deterministic, LLM-free. This is MONITORING — it never gates, so there is
# no Gate threshold here to defend; we only assert the honest read-out and that it raises no false alarm.

from __future__ import annotations

from cosmu.master.divergence import (
    DIVERGENCE_GAP_PCT,
    DIVERGENCE_MIN_DAYS,
    Divergence,
    divergence,
)


def test_constants_are_named_not_inline():
    # The warning band + display floor are named constants — NO inline magic number in the divergence path.
    assert DIVERGENCE_MIN_DAYS == 5.0
    assert DIVERGENCE_GAP_PCT == 5.0


def test_tracking_when_forward_matches_prorated_backtest():
    # Backtest made +30% over a 90-day OOS window → +1/3% per day → ~+3.33% expected over 10 marked days.
    # A marked +3.0% is within the band → "tracking".
    d = divergence(3.0, 10.0, 30.0, 90.0)
    assert isinstance(d, Divergence)
    assert d.status == "tracking"
    assert d.expected_return_pct == round(30.0 * (10.0 / 90.0), 4)
    assert d.gap_pct == round(3.0 - 30.0 * (10.0 / 90.0), 4)
    assert d.marked_days == 10.0


def test_diverging_when_forward_falls_far_short_of_backtest():
    # Backtest implied ~+11.11% over 40 marked days, but the live track is FLAT (0%) → gap < -DIVERGENCE_GAP_PCT.
    d = divergence(0.0, 40.0, 100.0, 360.0)
    assert d.status == "diverging"
    assert d.gap_pct < -DIVERGENCE_GAP_PCT


def test_diverging_is_symmetric_when_forward_runs_far_ahead():
    # An upside blow-out beyond the band is ALSO flagged (it's still "not tracking the backtest" — could be luck).
    d = divergence(20.0, 30.0, 5.0, 360.0)
    assert d.status == "diverging"
    assert d.gap_pct > DIVERGENCE_GAP_PCT


def test_insufficient_when_marked_window_too_short():
    # Below DIVERGENCE_MIN_DAYS we have no honest read → "insufficient", and NO false alarm (gap 0).
    d = divergence(50.0, 2.0, 1.0, 360.0)
    assert d.status == "insufficient"
    assert d.gap_pct == 0.0
    assert d.expected_return_pct == 0.0
    assert d.marked_days == 2.0


def test_min_days_boundary_is_inclusive():
    # Exactly DIVERGENCE_MIN_DAYS marked days is enough to compute (>= floor).
    at_floor = divergence(0.5, DIVERGENCE_MIN_DAYS, 6.0, 30.0)
    assert at_floor.status in ("tracking", "diverging")
    just_under = divergence(0.5, DIVERGENCE_MIN_DAYS - 0.01, 6.0, 30.0)
    assert just_under.status == "insufficient"


def test_insufficient_when_any_input_missing():
    # Day-0 / un-marked track: forward return is None → no read.
    assert divergence(None, 40.0, 30.0, 90.0).status == "insufficient"
    # No backtest return on the row.
    assert divergence(3.0, 40.0, None, 90.0).status == "insufficient"
    # No backtest OOS window length → can't pro-rate.
    assert divergence(3.0, 40.0, 30.0, None).status == "insufficient"


def test_insufficient_when_backtest_window_nonpositive():
    # A zero/negative OOS window can't be pro-rated → fail safe, no divide-by-zero.
    assert divergence(3.0, 40.0, 30.0, 0.0).status == "insufficient"
    assert divergence(3.0, 40.0, 30.0, -90.0).status == "insufficient"


def test_insufficient_on_nan_or_inf_inputs():
    # Degenerate numerics fail safe to no-alarm rather than emitting a bogus gap.
    assert divergence(float("nan"), 40.0, 30.0, 90.0).status == "insufficient"
    assert divergence(3.0, 40.0, float("inf"), 90.0).status == "insufficient"


def test_negative_forward_age_clamped_to_zero_and_insufficient():
    # A clock that reads negative (future origin) clamps to 0 marked days → insufficient.
    d = divergence(3.0, -10.0, 30.0, 90.0)
    assert d.status == "insufficient"
    assert d.marked_days == 0.0


def test_string_inputs_are_coerced():
    # The router may hand stringy DB values; they coerce like floats.
    d = divergence("3.0", "10", "30.0", "90")
    assert d.status == "tracking"
    assert d.marked_days == 10.0


def test_custom_thresholds_are_honored():
    # Thresholds are parameters (defaults = the named constants), never hardcoded inside the function.
    # A +4% marked vs ~+1.11% expected: gap ~+2.89pp — within the default 5pp band, but outside a tight 1pp band.
    base = divergence(4.0, 40.0, 10.0, 360.0)
    assert base.status == "tracking"
    tight = divergence(4.0, 40.0, 10.0, 360.0, gap_threshold_pct=1.0)
    assert tight.status == "diverging"
    # A relaxed display floor lets a shorter window compute.
    assert divergence(1.0, 3.0, 6.0, 30.0, min_days=2.0).status in ("tracking", "diverging")
