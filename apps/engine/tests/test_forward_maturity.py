# The forward-test maturity signal (master/forward_maturity.py): forward_age_days from the track's first mark,
# net_return_pct, and live_ready = (age >= FORWARD_TEST_MIN_DAYS AND net > 0). The leaderboard reads it advisorily;
# master/live_eligibility now consults the SAME flag as a HARD live-arming precondition (see
# test_live_eligibility_gate.py). These tests pin only the pure arithmetic + the fail-safe behavior. Deterministic,
# LLM-free.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import FORWARD_TEST_MIN_DAYS
from cosmu.master.forward_maturity import ForwardMaturity, forward_age_days, maturity


def _ago(days: float) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()


def test_constant_is_thirty_days_by_default():
    # The named config constant — NO inline magic number anywhere in the maturity path.
    assert FORWARD_TEST_MIN_DAYS == 30


def test_age_from_first_mark_is_calendar_days():
    now = datetime(2026, 6, 3, tzinfo=UTC)
    funded = datetime(2026, 5, 4, tzinfo=UTC).isoformat()  # 30 days earlier
    assert forward_age_days(funded, now=now) == 30.0


def test_age_fails_safe_to_zero_when_origin_missing_or_unparseable():
    # No track_opened ts yet, or a junk value → 0 days (a track is never more mature than its own clock).
    assert forward_age_days(None) == 0.0
    assert forward_age_days("") == 0.0
    assert forward_age_days("not-a-timestamp") == 0.0


def test_age_never_negative_for_a_future_origin():
    future = (datetime.now(tz=UTC) + timedelta(days=5)).isoformat()
    assert forward_age_days(future) == 0.0


def test_live_ready_requires_both_maturity_and_net_positive():
    # Matured AND net-positive → recommended.
    m = maturity(_ago(45), 3.2)
    assert isinstance(m, ForwardMaturity)
    assert m.live_ready is True
    assert m.min_days == FORWARD_TEST_MIN_DAYS

    # Matured but net-NEGATIVE → not ready (an underwater track is never recommended).
    assert maturity(_ago(45), -1.0).live_ready is False

    # Net-positive but TOO YOUNG → not ready (clock hasn't run long enough).
    assert maturity(_ago(10), 5.0).live_ready is False

    # Exactly net-zero is not "> 0" → not ready (strict net-of-fee positivity).
    assert maturity(_ago(45), 0.0).live_ready is False


def test_threshold_boundary_is_inclusive():
    # >= FORWARD_TEST_MIN_DAYS is inclusive: a track at exactly the threshold counts as matured.
    now = datetime(2026, 6, 3, tzinfo=UTC)
    at_threshold = (now - timedelta(days=FORWARD_TEST_MIN_DAYS)).isoformat()
    assert maturity(at_threshold, 1.0, now=now).live_ready is True
    just_under = (now - timedelta(days=FORWARD_TEST_MIN_DAYS) + timedelta(hours=1)).isoformat()
    assert maturity(just_under, 1.0, now=now).live_ready is False


def test_custom_min_days_override_is_honored():
    # The threshold is a parameter (default = the named constant), never hardcoded inside the function.
    assert maturity(_ago(20), 1.0, min_days=14).live_ready is True
    assert maturity(_ago(20), 1.0, min_days=60).live_ready is False
