"""Offline tests for the astro ephemeris data source.

All tests are fully deterministic (closed-form math, no network, no API key).
Verifies: point-in-time contract, no look-ahead, no fabrication (gaps absent not 0),
range constraints, and known-epoch spot-checks.

Non-causal control feature — wired honestly so the Gate can falsify it.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.astro_ephemeris import (
    TRANSFORM_VERSION,
    AstroEphemerisProvider,
    AstroEphemerisSource,
    _jd_from_dt,
    _jupiter_ecliptic_longitude_deg,
    _lunar_phase_fraction,
    _saturn_ecliptic_longitude_deg,
    _sun_ecliptic_longitude_deg,
    _sun_jupiter_aspect_deg,
    make_astro_sources,
)
from cosmu.data.sources.registry import SourceFeature


# ─── JD helper ────────────────────────────────────────────────────────────────

def test_jd_j2000_epoch():
    """J2000.0 = JD 2 451 545.0 exactly."""
    dt = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _jd_from_dt(dt) == pytest.approx(2_451_545.0, abs=1e-9)


def test_jd_monotone():
    """JD increases with time."""
    dt1 = datetime(2020, 1, 1, tzinfo=UTC)
    dt2 = datetime(2020, 1, 2, tzinfo=UTC)
    assert _jd_from_dt(dt2) > _jd_from_dt(dt1)
    assert _jd_from_dt(dt2) - _jd_from_dt(dt1) == pytest.approx(1.0, abs=1e-9)


# ─── Lunar phase ──────────────────────────────────────────────────────────────

def test_lunar_phase_fraction_range():
    """Illuminated fraction must be in [0, 1] for any date."""
    for year in (2000, 2010, 2020, 2024):
        for month in range(1, 13):
            dt = datetime(year, month, 15, 0, 0, 0, tzinfo=UTC)
            jd = _jd_from_dt(dt)
            f = _lunar_phase_fraction(jd)
            assert 0.0 <= f <= 1.0, f"Phase fraction {f} out of range for {dt}"


def test_lunar_phase_known_new_moon():
    """Near a known new moon (2024-01-11 UTC) phase fraction should be close to 0."""
    # Known new moon: 2024-01-11 11:57 UTC (NASA/USNO)
    dt = datetime(2024, 1, 11, 12, 0, 0, tzinfo=UTC)
    jd = _jd_from_dt(dt)
    f = _lunar_phase_fraction(jd)
    # Simplified model tolerance: accept < 0.10 (it's a new moon; exact zero is at conjunction)
    assert f < 0.10, f"Expected near-new-moon phase, got {f:.4f}"


def test_lunar_phase_known_full_moon():
    """Near a known full moon (2024-01-25 UTC) phase fraction should be close to 1."""
    # Known full moon: 2024-01-25 17:54 UTC (NASA/USNO)
    dt = datetime(2024, 1, 25, 18, 0, 0, tzinfo=UTC)
    jd = _jd_from_dt(dt)
    f = _lunar_phase_fraction(jd)
    # Accept > 0.90
    assert f > 0.90, f"Expected near-full-moon phase, got {f:.4f}"


def test_lunar_phase_deterministic():
    """Same inputs always produce the same output (no randomness, no state)."""
    dt = datetime(2022, 6, 14, 0, 0, 0, tzinfo=UTC)
    jd = _jd_from_dt(dt)
    a = _lunar_phase_fraction(jd)
    b = _lunar_phase_fraction(jd)
    assert a == b


# ─── Sun longitude ────────────────────────────────────────────────────────────

def test_sun_longitude_range():
    """Sun longitude must be in [0, 360)."""
    for doy in range(1, 366, 30):
        dt = datetime(2023, 1, 1, tzinfo=UTC) + timedelta(days=doy)
        jd = _jd_from_dt(dt)
        lon = _sun_ecliptic_longitude_deg(jd)
        assert 0.0 <= lon < 360.0, f"Sun longitude {lon} out of range"


def test_sun_longitude_vernal_equinox():
    """Near the vernal equinox (~2024-03-20) Sun longitude should be near 0°."""
    dt = datetime(2024, 3, 20, 3, 6, 0, tzinfo=UTC)  # USNO vernal equinox 2024
    jd = _jd_from_dt(dt)
    lon = _sun_ecliptic_longitude_deg(jd)
    # Accept ±2°
    assert abs(lon) < 2.0 or abs(lon - 360.0) < 2.0, f"Expected ~0°, got {lon:.2f}°"


def test_sun_longitude_summer_solstice():
    """Near the summer solstice (~2024-06-20) Sun longitude should be near 90°."""
    dt = datetime(2024, 6, 20, 20, 51, 0, tzinfo=UTC)
    jd = _jd_from_dt(dt)
    lon = _sun_ecliptic_longitude_deg(jd)
    assert abs(lon - 90.0) < 2.0, f"Expected ~90°, got {lon:.2f}°"


# ─── Jupiter / Saturn longitude ───────────────────────────────────────────────

def test_jupiter_longitude_range():
    """Jupiter longitude must be in [0, 360)."""
    for year in (1990, 2000, 2010, 2020, 2030):
        dt = datetime(year, 7, 1, tzinfo=UTC)
        jd = _jd_from_dt(dt)
        lon = _jupiter_ecliptic_longitude_deg(jd)
        assert 0.0 <= lon < 360.0, f"Jupiter longitude {lon} out of range for year {year}"


def test_saturn_longitude_range():
    """Saturn longitude must be in [0, 360)."""
    for year in (1990, 2000, 2010, 2020, 2030):
        dt = datetime(year, 7, 1, tzinfo=UTC)
        jd = _jd_from_dt(dt)
        lon = _saturn_ecliptic_longitude_deg(jd)
        assert 0.0 <= lon < 360.0, f"Saturn longitude {lon} out of range for year {year}"


def test_jupiter_period_approx_12_years():
    """Jupiter completes one orbit in ~11.86 years — longitude change should be ~360°."""
    dt1 = datetime(2000, 1, 1, tzinfo=UTC)
    dt2 = datetime(2011, 11, 1, tzinfo=UTC)  # ~11.83 years later
    jd1, jd2 = _jd_from_dt(dt1), _jd_from_dt(dt2)
    lon1 = _jupiter_ecliptic_longitude_deg(jd1)
    lon2 = _jupiter_ecliptic_longitude_deg(jd2)
    # Should have traveled ~360° (modular) → difference near 0 mod 360
    diff = (lon2 - lon1) % 360.0
    assert diff < 30.0 or diff > 330.0, f"Jupiter ~12yr advance not near 360°: diff={diff:.1f}°"


# ─── Sun–Jupiter aspect ───────────────────────────────────────────────────────

def test_sun_jupiter_aspect_range():
    """Aspect must be in [0, 180]."""
    for month in range(1, 13):
        dt = datetime(2020, month, 1, tzinfo=UTC)
        jd = _jd_from_dt(dt)
        asp = _sun_jupiter_aspect_deg(jd)
        assert 0.0 <= asp <= 180.0, f"Aspect {asp} out of range"


# ─── AstroEphemerisProvider ───────────────────────────────────────────────────

def test_provider_unsupported_metric_returns_empty():
    provider = AstroEphemerisProvider()
    result = provider.fetch_series("BTCUSDT", "no_such_metric", limit=10)
    assert result == []


def test_provider_returns_correct_count():
    provider = AstroEphemerisProvider()
    pts = provider.fetch_series("BTCUSDT", "lunar_phase_fraction", limit=30)
    assert len(pts) == 30


def test_provider_ascending_order():
    provider = AstroEphemerisProvider()
    pts = provider.fetch_series("MARKET", "lunar_phase_fraction", limit=20)
    for i in range(1, len(pts)):
        assert pts[i].available_at > pts[i - 1].available_at, "Points not in ascending order"


def test_provider_available_at_equals_ts():
    """available_at must equal ts (both are day midnight UTC — point-in-time, no offset)."""
    provider = AstroEphemerisProvider()
    pts = provider.fetch_series("MARKET", "sun_longitude_deg", limit=10)
    for p in pts:
        assert p.ts == p.available_at, "ts and available_at must be equal (deterministic day-start)"


def test_provider_available_at_is_midnight_utc():
    """available_at must be midnight UTC (hour=0, minute=0, second=0) — deterministic day-start."""
    provider = AstroEphemerisProvider()
    pts = provider.fetch_series("MARKET", "sun_longitude_deg", limit=10)
    for p in pts:
        assert p.available_at.hour == 0
        assert p.available_at.minute == 0
        assert p.available_at.second == 0
        assert p.available_at.tzinfo is not None


def test_provider_symbol_ignored():
    """Symbol argument is ignored (sky is market-wide); result must be identical."""
    provider = AstroEphemerisProvider()
    pts_btc = provider.fetch_series("BTCUSDT", "lunar_phase_fraction", limit=5)
    pts_eth = provider.fetch_series("ETHUSDT", "lunar_phase_fraction", limit=5)
    assert [p.value for p in pts_btc] == [p.value for p in pts_eth]


def test_provider_all_metrics_range():
    """All supported metrics return values in expected ranges."""
    provider = AstroEphemerisProvider()
    pts_phase = provider.fetch_series("MARKET", "lunar_phase_fraction", limit=10)
    assert all(0.0 <= p.value <= 1.0 for p in pts_phase)

    pts_sun = provider.fetch_series("MARKET", "sun_longitude_deg", limit=10)
    assert all(0.0 <= p.value < 360.0 for p in pts_sun)

    pts_jup = provider.fetch_series("MARKET", "jupiter_longitude_deg", limit=10)
    assert all(0.0 <= p.value < 360.0 for p in pts_jup)

    pts_sat = provider.fetch_series("MARKET", "saturn_longitude_deg", limit=10)
    assert all(0.0 <= p.value < 360.0 for p in pts_sat)

    pts_asp = provider.fetch_series("MARKET", "sun_jupiter_aspect", limit=10)
    assert all(0.0 <= p.value <= 180.0 for p in pts_asp)


# ─── AstroEphemerisSource ─────────────────────────────────────────────────────

def test_source_query_returns_source_feature():
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    as_of = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    f = src.query("MARKET", as_of)
    assert isinstance(f, SourceFeature)
    assert f.name == "astro_lunar_phase"
    assert f.scope == "MARKET"
    assert f.value is not None
    assert 0.0 <= f.value <= 1.0


def test_source_no_lookahead():
    """available_at must be <= as_of; the future is never visible."""
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    # as_of = 2 days in the past relative to "now"; should return the last known day
    as_of = datetime.now(tz=UTC) - timedelta(days=2)
    f = src.query("MARKET", as_of)
    if f.available_at is not None:
        assert f.available_at <= as_of, "available_at must be <= as_of (no look-ahead)"


def test_source_gap_is_none_not_fabricated_for_out_of_epoch():
    """A query outside the valid epoch (year < 1000 or year > 3000) returns None.

    The ephemeris model is not valid outside this range; the source honestly returns
    None rather than fabricating a garbage value.  This proves the no-fabrication contract:
    a gap (unsupported date) is absent, not 0.
    """
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
        _provider=AstroEphemerisProvider(),
    )
    # Year 500: outside the valid epoch — must return None, not a fabricated value
    very_old = datetime(500, 6, 1, tzinfo=UTC)
    f = src.query("MARKET", very_old, limit=1)
    assert f.value is None, "Date outside valid epoch must yield None (absent), not a fabricated value"


def test_source_low_confidence():
    """Confidence < 0.5 and low_confidence == True (non-causal OSINT must earn its place via OOS)."""
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_source_transform_version_pinned():
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    f = src.query("MARKET", datetime.now(tz=UTC))
    assert f.transform_version == TRANSFORM_VERSION


def test_source_kind_osint():
    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    assert src.kind == "osint"


# ─── make_astro_sources factory ───────────────────────────────────────────────

def test_make_astro_sources_count():
    sources = make_astro_sources()
    names = {s.name for s in sources}
    assert "astro_lunar_phase" in names
    assert "astro_sun_longitude" in names
    assert "astro_jupiter_longitude" in names
    assert "astro_saturn_longitude" in names
    assert "astro_sun_jupiter_aspect" in names
    assert len(sources) == 5


def test_make_astro_sources_all_low_confidence():
    """Every astro source is low-confidence (non-causal OSINT)."""
    for src in make_astro_sources():
        assert src.low_confidence is True, f"{src.name} must be low_confidence"
        assert src.confidence < 0.5, f"{src.name} confidence must be < 0.5"


def test_make_astro_sources_prior_says_non_causal():
    """Every prior must contain the tag 'NON-CAUSAL CONTROL FEATURE'."""
    for src in make_astro_sources():
        assert "NON-CAUSAL CONTROL FEATURE" in src.prior, (
            f"{src.name} prior must contain 'NON-CAUSAL CONTROL FEATURE'"
        )


def test_make_astro_sources_all_queryable():
    """Every source from make_astro_sources() can be queried and returns a SourceFeature."""
    as_of = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    for src in make_astro_sources():
        f = src.query("MARKET", as_of)
        assert isinstance(f, SourceFeature), f"{src.name} query did not return SourceFeature"
        assert f.value is not None, f"{src.name} returned None value for an in-range date"
        assert f.available_at is not None and f.available_at <= as_of, (
            f"{src.name} available_at {f.available_at} is after as_of {as_of}"
        )


def test_make_astro_sources_transform_version_consistent():
    """All sources use the same pinned transform_version."""
    for src in make_astro_sources():
        assert src.transform_version == TRANSFORM_VERSION


# ─── DataSource protocol compliance ───────────────────────────────────────────

def test_astro_source_satisfies_datasource_protocol():
    """AstroEphemerisSource satisfies the DataSource protocol (duck-type check)."""
    from cosmu.data.sources.registry import DataSource

    src = AstroEphemerisSource(
        name="astro_lunar_phase",
        metric="lunar_phase_fraction",
        prior="NON-CAUSAL CONTROL FEATURE — test",
    )
    assert isinstance(src, DataSource), "AstroEphemerisSource must satisfy the DataSource protocol"


# ─── Registry integration ─────────────────────────────────────────────────────

def test_astro_sources_can_be_registered():
    """All astro sources can be registered in a DataSourceRegistry without error."""
    from cosmu.data.sources.registry import DataSourceRegistry

    reg = DataSourceRegistry()
    for src in make_astro_sources():
        reg.register(src)
    assert "astro_lunar_phase" in reg.names()
    assert "astro_sun_longitude" in reg.names()
    catalog = reg.discover()
    by_name = {c["name"]: c for c in catalog}
    for name in ("astro_lunar_phase", "astro_sun_longitude", "astro_jupiter_longitude",
                 "astro_saturn_longitude", "astro_sun_jupiter_aspect"):
        assert by_name[name]["low_confidence"] is True
        assert by_name[name]["kind"] == "osint"


def test_registry_query_no_lookahead():
    """Registry query returns available_at <= as_of for all astro sources."""
    from cosmu.data.sources.registry import DataSourceRegistry

    reg = DataSourceRegistry()
    for src in make_astro_sources():
        reg.register(src)

    as_of = datetime(2024, 3, 21, 6, 0, 0, tzinfo=UTC)
    for name in reg.names():
        if name.startswith("astro_"):
            f = reg.query(name, "MARKET", as_of)
            if f.available_at is not None:
                assert f.available_at <= as_of, (
                    f"{name}: available_at {f.available_at} > as_of {as_of}"
                )
