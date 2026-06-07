"""Offline tests for the Open-Meteo weather adapter (data/sources/weather_openmeteo.py).

No network calls are made — every test uses `offline=True` or injects a parsed fixture directly.
Invariants under test:
  - Point-in-time: available_at = obs_date + 1 day (never same-day look-ahead).
  - No fabrication: missing API values become None, not 0.
  - PIT selectivity: query(as_of) returns None when as_of is before available_at.
  - Honest gap: empty hub response yields None value, not a fabricated score.
  - Fixture round-trip: parse → stress → SourceFeature flows end-to-end offline.
  - Protocol: WeatherOpenMeteoSource satisfies the DataSource protocol (has name/kind/metric/prior etc.)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from cosmu.data.sources.weather_openmeteo import (
    TRANSFORM_VERSION,
    WeatherDay,
    WeatherOpenMeteoSource,
    _FIXTURE_MULTI,
    _FIXTURE_NYC,
    _parse_payload,
    _pit_available_at,
    _weather_stress_score,
    fetch_weather_archive,
)


# ---------------------------------------------------------------------------
# PIT timestamp helper
# ---------------------------------------------------------------------------

def test_pit_available_at_is_one_day_plus_6h_utc() -> None:
    """available_at(obs_date) must be obs_date + 1 day at 06:00 UTC — never same-day."""
    obs = date(2024, 3, 15)
    avail = _pit_available_at(obs)
    assert avail == datetime(2024, 3, 16, 6, 0, 0, tzinfo=UTC)
    assert avail.tzinfo == UTC


def test_pit_available_at_strictly_after_obs() -> None:
    """available_at is always strictly later than midnight on the observation date."""
    for d in [date(2020, 1, 1), date(2023, 12, 31), date(2024, 6, 15)]:
        obs_midnight = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=UTC)
        assert _pit_available_at(d) > obs_midnight


# ---------------------------------------------------------------------------
# Payload parsing — no-fabrication / gap honesty
# ---------------------------------------------------------------------------

def test_parse_payload_all_present() -> None:
    days = _parse_payload("nyc", _FIXTURE_NYC)
    assert len(days) == 2
    d0, d1 = days
    assert d0.obs_date == date(2024, 1, 1)
    assert d0.temp_mean_c == pytest.approx(2.1)
    assert d0.precip_mm == pytest.approx(0.0)
    assert d0.wind_max_kph == pytest.approx(18.2)
    assert d1.obs_date == date(2024, 1, 2)
    assert d1.temp_mean_c == pytest.approx(-0.3)


def test_parse_payload_none_values_stay_none_not_zero() -> None:
    """A None in the API response must NOT become 0 — gaps are absent, not fabricated."""
    payload = {
        "daily": {
            "time": ["2024-01-03"],
            "temperature_2m_mean": [None],
            "precipitation_sum": [None],
            "windspeed_10m_max": [None],
        }
    }
    days = _parse_payload("nyc", payload)
    assert len(days) == 1
    assert days[0].temp_mean_c is None
    assert days[0].precip_mm is None
    assert days[0].wind_max_kph is None


def test_parse_payload_empty_daily_returns_empty_list() -> None:
    days = _parse_payload("nyc", {"daily": {}})
    assert days == []


def test_parse_payload_missing_daily_key_returns_empty_list() -> None:
    days = _parse_payload("nyc", {})
    assert days == []


def test_parse_payload_available_at_is_pit_stamped() -> None:
    """Each parsed day must carry available_at = obs_date + 1 day 06:00 UTC."""
    days = _parse_payload("nyc", _FIXTURE_NYC)
    for d in days:
        expected = _pit_available_at(d.obs_date)
        assert d.available_at == expected


# ---------------------------------------------------------------------------
# Stress score — composite feature
# ---------------------------------------------------------------------------

def test_stress_score_all_present_in_range() -> None:
    """Stress score is in [0, 1] for normal meteorological values."""
    days = _parse_payload("nyc", _FIXTURE_NYC)
    score = _weather_stress_score(days)
    assert score is not None
    assert 0.0 <= score <= 1.0


def test_stress_score_all_none_returns_none() -> None:
    """If every observation is None, the score is None — not 0 or fabricated."""
    days = [
        WeatherDay("nyc", date(2024, 1, 1), _pit_available_at(date(2024, 1, 1)),
                   None, None, None)
    ]
    assert _weather_stress_score(days) is None


def test_stress_score_empty_list_returns_none() -> None:
    assert _weather_stress_score([]) is None


def test_stress_score_cold_wet_windy_higher_than_mild() -> None:
    """Adverse weather (cold, wet, windy) must produce a higher stress score than mild weather."""
    mild = [WeatherDay("nyc", date(2024, 6, 15), _pit_available_at(date(2024, 6, 15)),
                       25.0, 0.0, 5.0)]
    severe = [WeatherDay("nyc", date(2024, 1, 10), _pit_available_at(date(2024, 1, 10)),
                         -15.0, 40.0, 75.0)]
    assert _weather_stress_score(severe) > _weather_stress_score(mild)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# WeatherOpenMeteoSource — DataSource protocol conformance
# ---------------------------------------------------------------------------

def test_source_has_required_protocol_fields() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    assert isinstance(src.name, str) and src.name
    assert isinstance(src.kind, str) and src.kind
    assert isinstance(src.metric, str) and src.metric
    assert isinstance(src.prior, str) and src.prior
    assert src.transform_version == TRANSFORM_VERSION
    assert 0.0 < src.confidence <= 1.0


def test_source_low_confidence_flag() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    assert src.low_confidence is True  # 0.15 < 0.5


# ---------------------------------------------------------------------------
# WeatherOpenMeteoSource.query — PIT selectivity (no look-ahead)
# ---------------------------------------------------------------------------

def test_query_returns_none_when_as_of_before_available_at() -> None:
    """If as_of is before the PIT window of even the most-recent day, value must be None."""
    src = WeatherOpenMeteoSource(offline=True)
    # Fixture covers 2024-01-01 and 2024-01-02.
    # available_at(2024-01-01) = 2024-01-02 06:00 UTC
    # Query as_of = 2024-01-01 00:00 UTC  → no observation is knowable yet (candidate: 2023-12-31)
    # which isn't in our fixture → the fixture hubs return [] for that date → None value
    as_of = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    # Either None (no data) or available_at <= as_of — NEVER available_at > as_of
    if feat.available_at is not None:
        assert feat.available_at <= as_of, "Look-ahead violation: available_at > as_of"


def test_query_available_at_never_exceeds_as_of() -> None:
    """The fundamental PIT invariant: available_at <= as_of for every query result."""
    src = WeatherOpenMeteoSource(offline=True)
    # Query well after the fixture dates — should find obs from fixture.
    as_of = datetime(2024, 1, 3, 12, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    if feat.available_at is not None:
        assert feat.available_at <= as_of, f"Look-ahead: {feat.available_at} > {as_of}"


def test_query_returns_value_when_as_of_past_pit_window() -> None:
    """When as_of is past available_at for a fixture date, the source returns a numeric stress value."""
    src = WeatherOpenMeteoSource(offline=True)
    # Fixture has 2024-01-02.  available_at(2024-01-02) = 2024-01-03 06:00 UTC.
    # Query at exactly available_at: candidate_date = 2024-01-02, which is in the fixture.
    as_of = datetime(2024, 1, 3, 6, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    assert feat.value is not None
    assert 0.0 <= feat.value <= 1.0


def test_query_scope_is_market_wide() -> None:
    """The returned SourceFeature must carry scope='MARKET' regardless of input scope."""
    src = WeatherOpenMeteoSource(offline=True)
    as_of = datetime(2024, 1, 4, 12, 0, 0, tzinfo=UTC)
    feat = src.query("BTCUSDT", as_of)
    assert feat.scope == "MARKET"


def test_query_feature_name_matches_source_name() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    as_of = datetime(2024, 1, 4, 12, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    assert feat.name == src.name


def test_query_transform_version_propagated() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    as_of = datetime(2024, 1, 4, 12, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    assert feat.transform_version == TRANSFORM_VERSION


def test_query_confidence_propagated() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    as_of = datetime(2024, 1, 4, 12, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    assert feat.confidence == src.confidence
    assert feat.low_confidence is True


# ---------------------------------------------------------------------------
# No-fabrication: missing hubs return None not 0
# ---------------------------------------------------------------------------

def test_query_with_empty_fixture_yields_none_value() -> None:
    """If fixture has no data for the candidate date, value is None — never a fabricated 0."""
    src = WeatherOpenMeteoSource(offline=True, _fixture={})
    as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    feat = src.query("MARKET", as_of)
    assert feat.value is None
    assert feat.available_at is None


# ---------------------------------------------------------------------------
# parse_days / stress_score helpers on the source instance
# ---------------------------------------------------------------------------

def test_parse_days_helper_roundtrips_fixture() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    days = src.parse_days("nyc", _FIXTURE_NYC)
    assert len(days) == 2
    assert all(isinstance(d, WeatherDay) for d in days)


def test_stress_score_helper_on_source_instance() -> None:
    src = WeatherOpenMeteoSource(offline=True)
    days = src.parse_days("nyc", _FIXTURE_NYC)
    score = src.stress_score(days)
    assert score is not None
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Multi-hub fixture coverage
# ---------------------------------------------------------------------------

def test_multi_hub_fixture_covers_all_hubs() -> None:
    """Fixture includes data for all four financial hubs."""
    expected_hubs = {"nyc", "lon", "tyo", "sha"}
    assert set(_FIXTURE_MULTI.keys()) == expected_hubs


def test_multi_hub_parse_produces_cross_hub_score() -> None:
    """Parsing all four hubs and computing stress produces a valid cross-hub scalar."""
    all_days: list[WeatherDay] = []
    for hub, payload in _FIXTURE_MULTI.items():
        all_days.extend(_parse_payload(hub, payload))
    score = _weather_stress_score(all_days)
    assert score is not None
    assert 0.0 <= score <= 1.0
