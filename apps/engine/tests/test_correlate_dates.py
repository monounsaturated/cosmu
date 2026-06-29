# Date-normalization + probability-series tests for the correlation lane. Pure, deterministic, offline: every
# parse is pinned to a fixed `as_of` so there are no clock surprises.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.correlate.dates import (
    detect_moves,
    latest_move,
    normalize_prob_series,
    normalize_resolution,
)
from cosmu.data.altdata import AltDataPoint

_ASOF = datetime(2026, 6, 29, tzinfo=UTC)  # the fixed "now" every test resolves against


# ── resolution-string parsing ────────────────────────────────────────────────────────────────────────────────

def test_absolute_month_day_before_phrase() -> None:
    r = normalize_resolution("Will the Strait of Hormuz reopen before July 1?", as_of=_ASOF)
    assert r.deadline == datetime(2026, 7, 1, tzinfo=UTC)
    assert r.days_to_event == 2.0
    assert r.basis == "absolute"
    assert r.horizon_bucket == "near"


def test_iso_date() -> None:
    r = normalize_resolution("resolves 2026-07-01", as_of=_ASOF)
    assert r.deadline == datetime(2026, 7, 1, tzinfo=UTC)
    assert r.basis == "absolute"


def test_day_month_year_and_ordinals() -> None:
    assert normalize_resolution("1 July 2026", as_of=_ASOF).deadline == datetime(2026, 7, 1, tzinfo=UTC)
    assert normalize_resolution("July 1st", as_of=_ASOF).deadline == datetime(2026, 7, 1, tzinfo=UTC)
    assert normalize_resolution("December 31, 2026", as_of=_ASOF).deadline == datetime(2026, 12, 31, tzinfo=UTC)


def test_year_inference_next_occurrence() -> None:
    # Jan 5 has already passed in 2026 → infer the NEXT occurrence (2027).
    assert normalize_resolution("January 5", as_of=_ASOF).deadline.year == 2027
    # Dec 5 is still ahead in 2026 → stay this year.
    assert normalize_resolution("December 5", as_of=_ASOF).deadline.year == 2026


def test_relative_durations() -> None:
    assert normalize_resolution("in the next 7 days", as_of=_ASOF).deadline == _ASOF + timedelta(days=7)
    assert normalize_resolution("within 24 hours", as_of=_ASOF).deadline == _ASOF + timedelta(hours=24)
    three_mo = normalize_resolution("in 3 months", as_of=_ASOF)
    assert three_mo.deadline == _ASOF + timedelta(days=90)
    assert three_mo.basis == "relative"
    assert three_mo.horizon_bucket == "far"  # 90d is NOT < 90 → far (boundary check)


def test_relative_buckets() -> None:
    assert normalize_resolution("within 24 hours", as_of=_ASOF).horizon_bucket == "imminent"
    assert normalize_resolution("in the next 7 days", as_of=_ASOF).horizon_bucket == "near"
    assert normalize_resolution("in 45 days", as_of=_ASOF).horizon_bucket == "medium"


def test_named_buckets() -> None:
    eoy = normalize_resolution("by end of year", as_of=_ASOF)
    assert eoy.deadline == datetime(2026, 12, 31, tzinfo=UTC)
    assert eoy.basis == "named"
    eom = normalize_resolution("end of July", as_of=_ASOF)
    assert eom.deadline.month == 7 and eom.deadline.day == 31
    assert eom.basis == "named"


def test_month_year_no_day() -> None:
    r = normalize_resolution("Will BTC hit $100k by August 2026?", as_of=_ASOF)
    # "$100k" must NOT parse as a date; "August 2026" → end of August.
    assert r.deadline.year == 2026 and r.deadline.month == 8 and r.deadline.day == 31
    assert r.basis == "named"


def test_unparseable_is_honest_not_raising() -> None:
    r = normalize_resolution("when it happens, soon-ish", as_of=_ASOF)
    assert r.deadline is None
    assert r.days_to_event is None
    assert r.basis == "unparsed"
    assert r.horizon_bucket == "unknown"


def test_empty_string_is_safe() -> None:
    r = normalize_resolution("", as_of=_ASOF)
    assert r.deadline is None and r.basis == "unparsed"


# ── probability-series normalization ─────────────────────────────────────────────────────────────────────────

def _t(day: int) -> datetime:
    return datetime(2026, 6, day, tzinfo=UTC)


def test_normalize_sorts_dedups_clips_and_drops_bad() -> None:
    raw = [
        (_t(3), 0.5),
        (_t(1), 1.5),    # out of range → clipped to 1.0
        (_t(2), -0.2),   # out of range → clipped to 0.0
        (_t(1), 0.4),    # duplicate ts → LAST value (0.4) wins, supersedes the 1.5
        (_t(4), None),   # missing → dropped, never zero-filled
        (_t(5), float("nan")),  # NaN → dropped
    ]
    series = normalize_prob_series(raw)
    assert [(p.ts.day, p.prob) for p in series] == [(1, 0.4), (2, 0.0), (3, 0.5)]


def test_normalize_accepts_altdatapoints() -> None:
    pts = [
        AltDataPoint(ts=_t(2), available_at=_t(2), value=0.6),
        AltDataPoint(ts=_t(1), available_at=_t(1), value=0.3),
    ]
    series = normalize_prob_series(pts)
    assert [(p.ts.day, p.prob) for p in series] == [(1, 0.3), (2, 0.6)]


def test_normalize_empty() -> None:
    assert normalize_prob_series([]) == []


# ── move detection ───────────────────────────────────────────────────────────────────────────────────────────

def test_latest_move_is_last_two_points() -> None:
    series = normalize_prob_series([(_t(1), 0.30), (_t(2), 0.32), (_t(3), 0.45)])
    mv = latest_move(series)
    assert mv is not None
    assert mv.prev_prob == 0.32 and mv.prob == 0.45
    assert abs(mv.delta - 0.13) < 1e-9
    assert mv.abs_delta > 0


def test_latest_move_needs_two_points() -> None:
    assert latest_move(normalize_prob_series([(_t(1), 0.5)])) is None
    assert latest_move([]) is None


def test_detect_moves_threshold_and_span() -> None:
    series = normalize_prob_series([(_t(1), 0.30), (_t(2), 0.33), (_t(3), 0.45), (_t(10), 0.55)])
    # default 5pp floor: the 0.30→0.33 (3pp) move is filtered; 0.33→0.45 (12pp) and 0.45→0.55 (10pp) survive.
    moves = detect_moves(series)
    assert len(moves) == 2
    assert all(m.abs_delta >= 0.05 for m in moves)
    # max_span drops the 0.45→0.55 move (7-day span) but keeps the 1-day 0.33→0.45 move.
    near = detect_moves(series, max_span=timedelta(days=2))
    assert len(near) == 1 and near[0].prev_prob == 0.33


def test_detect_moves_signed() -> None:
    series = normalize_prob_series([(_t(1), 0.50), (_t(2), 0.30)])
    moves = detect_moves(series, min_abs_delta=0.05)
    assert len(moves) == 1 and moves[0].delta < 0  # a DROP is a signed negative move
