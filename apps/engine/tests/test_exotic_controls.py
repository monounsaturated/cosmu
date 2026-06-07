"""Offline tests for the exotic orthogonality-control DataSources:
USGS earthquake (count + max-magnitude) and NOAA Kp geomagnetic index.

No network calls — all tests use the bundled offline fixtures (offline=True).

Invariants verified:
  - Protocol: each source satisfies the DataSource protocol.
  - PIT / no look-ahead: available_at == as_of (live snapshot; value is only knowable at
    the moment it is taken — the same convention as osint_adsb).
  - No fabrication: a gap (no magnitude data / no parseable Kp rows) yields value=None, not 0.
  - low_confidence == True for all three sources (orthogonality controls).
  - Transform versions are pinned (re-runnable survivors).
  - Feature keys appear in the feature_names() vocabulary once registered.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cosmu.data.sources.exotic_controls import (
    NOAA_KP_TRANSFORM_VERSION,
    USGS_TRANSFORM_VERSION,
    NoaaKpIndexSource,
    UsgsEarthquakeSource,
    UsgsMaxMagnitudeSource,
    _parse_kp,
    _parse_usgs,
)
from cosmu.data.sources.registry import DataSource, DataSourceRegistry

_AS_OF = datetime(2024, 3, 15, 14, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Pure parse helpers
# ---------------------------------------------------------------------------

class TestParseUsgs:
    def test_count_and_max_mag_from_fixture(self):
        from cosmu.data.sources.exotic_controls import _USGS_FIXTURE
        count, max_mag = _parse_usgs(_USGS_FIXTURE)
        # fixture: 5 events with mags [2.1, 3.5, 1.8, 5.2, 0.9]
        assert count == 5
        assert max_mag == pytest.approx(5.2)

    def test_empty_features_gives_zero_count_and_none_mag(self):
        count, max_mag = _parse_usgs({"features": []})
        assert count == 0
        assert max_mag is None  # gap, not 0

    def test_null_mags_give_none(self):
        payload = {"features": [
            {"properties": {"mag": None}},
            {"properties": {}},
        ]}
        count, max_mag = _parse_usgs(payload)
        assert count == 2
        assert max_mag is None  # absent data — not zero-filled

    def test_mixed_valid_and_null_mags(self):
        payload = {"features": [
            {"properties": {"mag": 4.0}},
            {"properties": {"mag": None}},
        ]}
        count, max_mag = _parse_usgs(payload)
        assert count == 2
        assert max_mag == pytest.approx(4.0)


class TestParseKp:
    def test_max_kp_from_fixture(self):
        from cosmu.data.sources.exotic_controls import _NOAA_KP_FIXTURE
        kp_max = _parse_kp(_NOAA_KP_FIXTURE)
        # fixture Kp values: 0.33, 1.67, 3.00, 2.33, 1.00, 0.67, 4.33, 2.00 → max = 4.33
        assert kp_max == pytest.approx(4.33)

    def test_empty_rows_give_none(self):
        assert _parse_kp([]) is None  # gap, not 0

    def test_unparseable_rows_give_none(self):
        assert _parse_kp([["2024-01-01 00:00:00", "N/A"], ["2024-01-01 03:00:00", ""]]) is None

    def test_short_rows_skipped(self):
        assert _parse_kp([[], ["only-one"]]) is None

    def test_mixed_valid_and_invalid(self):
        rows = [["t", "2.5"], ["t", "bad"], ["t", "3.0"]]
        assert _parse_kp(rows) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# UsgsEarthquakeSource
# ---------------------------------------------------------------------------

class TestUsgsEarthquakeSource:
    def _src(self) -> UsgsEarthquakeSource:
        return UsgsEarthquakeSource(offline=True)

    def test_protocol_satisfied(self):
        assert isinstance(self._src(), DataSource)

    def test_parse_count_and_max_mag_from_fixture(self):
        src = self._src()
        count, max_mag = src.parse_count_and_max_mag()
        assert count == 5
        assert max_mag == pytest.approx(5.2)

    def test_low_confidence(self):
        assert self._src().low_confidence is True
        assert self._src().confidence < 0.5

    def test_transform_version_pinned(self):
        assert self._src().transform_version == USGS_TRANSFORM_VERSION

    def test_pit_available_at_equals_as_of(self):
        """No look-ahead: available_at == as_of (live snapshot convention)."""
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.available_at == f.as_of == _AS_OF

    def test_value_from_fixture(self):
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.value == 5.0  # 5 events in fixture

    def test_scope_is_market_wide(self):
        src = self._src()
        f = src.query("BTCUSDT", _AS_OF)
        assert f.scope == "MARKET"

    def test_empty_fixture_gives_zero_count(self):
        """0 events is a VALID reading (not a gap); value=0, not None."""
        src = UsgsEarthquakeSource(offline=True)
        src._fixture = {"features": []}
        f = src.query("MARKET", _AS_OF)
        assert f.value == 0.0
        # still has an available_at (value is present, just zero events)
        assert f.available_at == _AS_OF

    def test_no_fabrication_count_is_never_negative(self):
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.value is not None and f.value >= 0.0

    def test_prior_contains_orthogonality_control(self):
        assert "ORTHOGONALITY CONTROL" in self._src().prior
        assert "Must be killed by the Gate" in self._src().prior

    def test_kind_is_osint(self):
        assert self._src().kind == "osint"


# ---------------------------------------------------------------------------
# UsgsMaxMagnitudeSource
# ---------------------------------------------------------------------------

class TestUsgsMaxMagnitudeSource:
    def _src(self) -> UsgsMaxMagnitudeSource:
        return UsgsMaxMagnitudeSource(offline=True)

    def test_protocol_satisfied(self):
        assert isinstance(self._src(), DataSource)

    def test_parse_max_magnitude_from_fixture(self):
        src = self._src()
        assert src.parse_max_magnitude() == pytest.approx(5.2)

    def test_low_confidence(self):
        assert self._src().low_confidence is True
        assert self._src().confidence < 0.5

    def test_pit_available_at_equals_as_of(self):
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.available_at == f.as_of == _AS_OF

    def test_value_from_fixture(self):
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.value == pytest.approx(5.2)

    def test_no_fabrication_null_mags_give_none_value(self):
        """A gap (no magnitude data) must yield value=None, not 0 — absent data is never 0-filled."""
        src = UsgsMaxMagnitudeSource(offline=True)
        src._fixture = {"features": [{"properties": {"mag": None}}, {"properties": {}}]}
        max_mag = src.parse_max_magnitude()
        assert max_mag is None
        f = src.query("MARKET", _AS_OF)
        assert f.value is None
        assert f.available_at is None  # gap: no available_at when value is absent

    def test_no_fabrication_empty_features_give_none(self):
        src = UsgsMaxMagnitudeSource(offline=True)
        src._fixture = {"features": []}
        f = src.query("MARKET", _AS_OF)
        assert f.value is None

    def test_scope_is_market_wide(self):
        src = self._src()
        f = src.query("ETHUSDT", _AS_OF)
        assert f.scope == "MARKET"

    def test_prior_contains_orthogonality_control(self):
        assert "ORTHOGONALITY CONTROL" in self._src().prior


# ---------------------------------------------------------------------------
# NoaaKpIndexSource
# ---------------------------------------------------------------------------

class TestNoaaKpIndexSource:
    def _src(self) -> NoaaKpIndexSource:
        return NoaaKpIndexSource(offline=True)

    def test_protocol_satisfied(self):
        assert isinstance(self._src(), DataSource)

    def test_parse_kp_max_from_fixture(self):
        src = self._src()
        assert src.parse_kp_max() == pytest.approx(4.33)

    def test_low_confidence(self):
        assert self._src().low_confidence is True
        assert self._src().confidence < 0.5

    def test_transform_version_pinned(self):
        assert self._src().transform_version == NOAA_KP_TRANSFORM_VERSION

    def test_pit_available_at_equals_as_of(self):
        """No look-ahead: available_at == as_of (live snapshot convention)."""
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.available_at == f.as_of == _AS_OF

    def test_value_from_fixture(self):
        src = self._src()
        f = src.query("MARKET", _AS_OF)
        assert f.value == pytest.approx(4.33)

    def test_scope_is_market_wide(self):
        src = self._src()
        f = src.query("BTCUSDT", _AS_OF)
        assert f.scope == "MARKET"

    def test_no_fabrication_empty_rows_give_none(self):
        """Empty fixture → value=None (gap), not 0."""
        src = NoaaKpIndexSource(offline=True)
        src._fixture = []
        f = src.query("MARKET", _AS_OF)
        assert f.value is None
        assert f.available_at is None  # gap: no available_at when value is absent

    def test_no_fabrication_unparseable_rows_give_none(self):
        src = NoaaKpIndexSource(offline=True)
        src._fixture = [["2024-01-01 00:00:00", "N/A"]]
        f = src.query("MARKET", _AS_OF)
        assert f.value is None

    def test_prior_contains_orthogonality_control(self):
        assert "ORTHOGONALITY CONTROL" in self._src().prior
        assert "Must be killed by the Gate" in self._src().prior

    def test_kind_is_osint(self):
        assert self._src().kind == "osint"


# ---------------------------------------------------------------------------
# Registry round-trip
# ---------------------------------------------------------------------------

class TestExoticControlsRegistry:
    def _reg(self) -> DataSourceRegistry:
        reg = DataSourceRegistry()
        reg.register(UsgsEarthquakeSource(offline=True))
        reg.register(UsgsMaxMagnitudeSource(offline=True))
        reg.register(NoaaKpIndexSource(offline=True))
        return reg

    def test_all_three_register_and_satisfy_protocol(self):
        reg = self._reg()
        assert "usgs_earthquake_count" in reg.names()
        assert "usgs_max_magnitude" in reg.names()
        assert "noaa_kp_index" in reg.names()
        for name in reg.names():
            assert isinstance(reg.get(name), DataSource)

    def test_registry_discover_all_low_confidence(self):
        catalog = {e["name"]: e for e in self._reg().discover()}
        for key in ("usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index"):
            assert catalog[key]["low_confidence"] is True, f"{key} must be low_confidence"
            assert catalog[key]["kind"] == "osint"

    def test_registry_pit_query_returns_values(self):
        reg = self._reg()
        f_count = reg.query("usgs_earthquake_count", "MARKET", _AS_OF)
        assert f_count.value is not None
        assert f_count.available_at == _AS_OF  # no look-ahead

        f_kp = reg.query("noaa_kp_index", "MARKET", _AS_OF)
        assert f_kp.value is not None
        assert f_kp.available_at == _AS_OF

    def test_feature_names_include_exotic_controls(self):
        """The three feature keys must appear in feature_names() (after registration)."""
        from cosmu.config.feature_registry import feature_names

        names = feature_names()
        for key in ("usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index"):
            assert key in names, (
                f"'{key}' missing from feature_registry.  "
                "Add the FeatureDefinition entries via the registration snippet in the PR body."
            )
