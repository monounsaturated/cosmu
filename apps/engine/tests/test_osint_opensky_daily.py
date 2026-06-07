"""Offline, deterministic tests for the OpenSky daily flight-count DataSource.

Verified invariants:
  1. PIT contract: available_at = flight_date + 1 day (next-day); NEVER look-ahead.
  2. Gap honesty: a missing day returns value=None (not 0).
  3. as_of earlier than first available datum → value=None, available_at=None.
  4. parse_count deduplicates ICAO-24 (same aircraft seen in multiple records = 1).
  5. low_confidence=True (confidence 0.10 < 0.5).
  6. transform_version is the pinned string.
  7. query() uses the latest day whose available_at ≤ as_of (never the next day — no look-ahead).
  8. No HTTP calls in any test (offline=True throughout).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from cosmu.data.sources.osint_opensky_daily import (
    TRANSFORM_VERSION,
    OpenSkyDailyFlightsSource,
    _FIXTURE_DAILY_COUNTS,
    _FIXTURE_WINDOW_FLIGHTS,
    _day_to_unix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_src(**kwargs) -> OpenSkyDailyFlightsSource:
    """Return an offline source; tests pass a custom fixture to avoid coupling to the global default."""
    defaults = dict(offline=True)
    defaults.update(kwargs)
    return OpenSkyDailyFlightsSource(**defaults)


_JAN01 = datetime(2024, 1, 1, tzinfo=UTC)   # flight_date 2024-01-01, available_at 2024-01-02 00:00 UTC
_JAN02 = datetime(2024, 1, 2, tzinfo=UTC)
_JAN03 = datetime(2024, 1, 3, tzinfo=UTC)   # gap day — absent from fixture
_JAN04 = datetime(2024, 1, 4, tzinfo=UTC)
_JAN05 = datetime(2024, 1, 5, tzinfo=UTC)


# ---------------------------------------------------------------------------
# PIT: available_at = flight_date + 1 day
# ---------------------------------------------------------------------------

class TestPITContract:
    def test_available_at_is_next_day_midnight(self):
        src = _make_src()
        avail = src._available_at(date(2024, 1, 1))
        assert avail == datetime(2024, 1, 2, tzinfo=UTC), "available_at must be the next UTC midnight"

    def test_as_of_exactly_at_available_at_sees_the_day(self):
        """as_of == available_at(D) → D is knowable (boundary is inclusive)."""
        src = _make_src()
        # available_at for 2024-01-01 = 2024-01-02 00:00 UTC
        as_of = datetime(2024, 1, 2, tzinfo=UTC)
        f = src.query("MARKET", as_of)
        assert f.value == float(_FIXTURE_DAILY_COUNTS["2024-01-01"])
        assert f.available_at == as_of

    def test_as_of_one_second_before_available_at_cannot_see_the_day(self):
        """as_of = available_at(D) - 1 second → D is NOT knowable (no look-ahead)."""
        src = _make_src()
        # available_at for 2024-01-04 is 2024-01-05 00:00 UTC; ask one second before
        as_of = datetime(2024, 1, 4, 23, 59, 59, tzinfo=UTC)
        f = src.query("MARKET", as_of)
        # The latest day whose available_at ≤ as_of is 2024-01-03 (= available_at 2024-01-04 00:00 UTC)
        # BUT 2024-01-03 is a gap → value is None.  Either way, 2024-01-04 data must NOT be visible.
        if f.value is not None:
            assert f.value != float(_FIXTURE_DAILY_COUNTS["2024-01-04"]), (
                "LOOK-AHEAD: 2024-01-04 data must not be visible at 2024-01-04T23:59:59Z"
            )

    def test_available_at_on_feature_equals_source_available_at(self):
        """The SourceFeature.available_at matches the source's own _available_at() for the flight day."""
        src = _make_src()
        as_of = _JAN05  # 2024-01-05 00:00 UTC → latest knowable day = 2024-01-04
        f = src.query("MARKET", as_of)
        expected_avail = src._available_at(date(2024, 1, 4))
        assert f.available_at == expected_avail


# ---------------------------------------------------------------------------
# Gap honesty: missing day → None, not 0
# ---------------------------------------------------------------------------

class TestGapHonesty:
    def test_missing_day_returns_none_not_zero(self):
        """2024-01-03 is absent from the fixture; as_of = 2024-01-04 00:00 returns None (gap)."""
        src = _make_src()
        # as_of = 2024-01-04 00:00 UTC → latest knowable day = 2024-01-03
        # 2024-01-03 is absent from _FIXTURE_DAILY_COUNTS → value must be None
        as_of = _JAN04
        f = src.query("MARKET", as_of)
        assert f.value is None, "A gap day must yield value=None, NEVER 0"
        # available_at is still set (to the day+1 boundary that was queried)
        assert f.available_at == datetime(2024, 1, 4, tzinfo=UTC)

    def test_fetch_count_for_date_gap_returns_none(self):
        src = _make_src()
        result = src.fetch_count_for_date(date(2024, 1, 3))
        assert result is None, "fetch_count_for_date must return None for absent day, not 0"

    def test_fetch_count_for_present_day_returns_int(self):
        src = _make_src()
        result = src.fetch_count_for_date(date(2024, 1, 1))
        assert result == _FIXTURE_DAILY_COUNTS["2024-01-01"]


# ---------------------------------------------------------------------------
# Before-any-data case
# ---------------------------------------------------------------------------

class TestBeforeAnyData:
    def test_as_of_before_2015_returns_none(self):
        """as_of before the OpenSky data era → no datum knowable → value=None, available_at=None."""
        src = _make_src()
        ancient = datetime(2010, 1, 1, tzinfo=UTC)
        f = src.query("MARKET", ancient)
        assert f.value is None
        assert f.available_at is None

    def test_as_of_equal_to_day_zero_plus_one_sees_nothing_useful(self):
        """A fixture with only 2024-01-01+; asking at 2024-01-01T12:00 → latest knowable = 2023-12-31
        which is absent (before fixture start) → None."""
        src = _make_src()
        as_of = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        f = src.query("MARKET", as_of)
        # _latest_knowable_day returns 2023-12-31; fixture has no entry → None
        assert f.value is None


# ---------------------------------------------------------------------------
# parse_count: deduplication
# ---------------------------------------------------------------------------

class TestParseCount:
    def test_deduplicates_icao24(self):
        """Two records with the same icao24 → counted once (unique aircraft)."""
        src = _make_src()
        payload = [
            {"icao24": "abc123", "firstSeen": 0},
            {"icao24": "abc123", "firstSeen": 10},  # duplicate
            {"icao24": "def456", "firstSeen": 0},
        ]
        assert src.parse_count(payload) == 2

    def test_case_insensitive_icao24(self):
        """ICAO-24 matching is case-insensitive (OpenSky may return mixed case)."""
        src = _make_src()
        payload = [
            {"icao24": "ABC123"},
            {"icao24": "abc123"},  # same aircraft, different case
        ]
        assert src.parse_count(payload) == 1

    def test_missing_icao24_field_skipped(self):
        src = _make_src()
        payload = [{"icao24": "a1b2c3"}, {"firstSeen": 0}]  # second entry has no icao24
        assert src.parse_count(payload) == 1

    def test_default_fixture_has_expected_unique_count(self):
        """The bundled _FIXTURE_WINDOW_FLIGHTS has 2 unique ICAO-24 (a1b2c3, d4e5f6)."""
        src = _make_src()
        assert src.parse_count() == 2

    def test_empty_payload_returns_zero(self):
        src = _make_src()
        assert src.parse_count([]) == 0


# ---------------------------------------------------------------------------
# Metadata and protocol
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_low_confidence_is_true(self):
        src = _make_src()
        assert src.low_confidence is True
        assert src.confidence < 0.5

    def test_transform_version_is_pinned(self):
        src = _make_src()
        assert src.transform_version == TRANSFORM_VERSION

    def test_feature_name_is_snake_case(self):
        src = _make_src()
        assert src.name == "opensky_daily_flights"
        assert "_" in src.name  # snake_case
        assert " " not in src.name

    def test_kind_is_osint(self):
        src = _make_src()
        assert src.kind == "osint"

    def test_prior_mentions_low_confidence(self):
        src = _make_src()
        prior_lower = src.prior.lower()
        assert "low" in prior_lower or "confidence" in prior_lower

    def test_query_returns_source_feature_with_correct_metadata(self):
        from cosmu.data.sources.registry import SourceFeature

        src = _make_src()
        as_of = _JAN02  # available_at for 2024-01-01 is 2024-01-02 00:00 UTC → visible
        f = src.query("MARKET", as_of)
        assert isinstance(f, SourceFeature)
        assert f.name == "opensky_daily_flights"
        assert f.scope == "MARKET"
        assert f.transform_version == TRANSFORM_VERSION
        assert f.low_confidence is True
        assert f.confidence < 0.5


# ---------------------------------------------------------------------------
# DataSource protocol compliance
# ---------------------------------------------------------------------------

class TestDataSourceProtocol:
    def test_satisfies_datasource_protocol(self):
        from cosmu.data.sources.registry import DataSource

        src = _make_src()
        assert isinstance(src, DataSource)

    def test_registerable_in_registry(self):
        from cosmu.data.sources.registry import DataSourceRegistry

        src = _make_src()
        reg = DataSourceRegistry()
        reg.register(src)
        assert "opensky_daily_flights" in reg.names()
        catalog = reg.discover()
        entry = next(c for c in catalog if c["name"] == "opensky_daily_flights")
        assert entry["low_confidence"] is True
        assert entry["kind"] == "osint"


# ---------------------------------------------------------------------------
# _day_to_unix helper
# ---------------------------------------------------------------------------

class TestDayToUnix:
    def test_2024_01_01_midnight_utc(self):
        """2024-01-01 00:00 UTC = 1704067200 seconds since epoch."""
        assert _day_to_unix(date(2024, 1, 1)) == 1_704_067_200

    def test_monotone_consecutive_days(self):
        d = date(2024, 1, 1)
        prev = _day_to_unix(d)
        for _ in range(5):
            d += timedelta(days=1)
            curr = _day_to_unix(d)
            assert curr == prev + 86_400
            prev = curr
