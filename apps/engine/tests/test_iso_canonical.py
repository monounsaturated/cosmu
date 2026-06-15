# iso_utc is the SINGLE canonical timestamp form for the alt-data store's string<= point-in-time read. These
# pin that lexical order == chronological order can never drift from a naive / 'Z' / non-UTC vendor timestamp —
# the silent look-ahead class flagged in the cold-tier migration review.
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from cosmu.data._iso import CANON_RE, iso_utc


def test_naive_assumed_utc_and_offset_converted():
    aware = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    naive = datetime(2026, 6, 14, 12, 0, 0)                                       # no tzinfo
    plus2 = datetime(2026, 6, 14, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))  # same instant as `aware`
    assert iso_utc(naive) == iso_utc(aware)   # naive assumed UTC
    assert iso_utc(plus2) == iso_utc(aware)   # non-UTC offset converted to UTC


def test_always_canonical_shape_never_Z():
    for dt in (
        datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC),               # midnight, no fractional secs
        datetime(2026, 6, 14, 12, 30, 59, 123456, tzinfo=UTC),    # microseconds
        datetime(2026, 6, 14, 12, 0, 0),                          # naive
    ):
        s = iso_utc(dt)
        assert CANON_RE.match(s), s
        assert "Z" not in s and s.endswith("+00:00")


def test_idempotent_on_already_stored_form():
    # a row written by the old `.isoformat()` path (UTC-aware) round-trips UNCHANGED → not a reformat migration
    s = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC).isoformat()
    assert iso_utc(datetime.fromisoformat(s)) == s


def test_lexical_order_equals_chronological():
    a = iso_utc(datetime(2026, 6, 14, 11, 59, 59, tzinfo=UTC))
    b = iso_utc(datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC))
    c = iso_utc(datetime(2026, 6, 14, 12, 0, 0, 500000, tzinfo=UTC))
    assert a < b < c   # string compare matches time order across the second + fractional-second boundary
