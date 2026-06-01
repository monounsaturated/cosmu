"""The pluggable DataSourceRegistry + the OSINT ADS-B source. Registry discovery + point-in-time query
(latest value whose availability <= as_of, never look-ahead); AdsbDataSource parse + availability stamp +
offline fixture + low-confidence flag. All offline, no key, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.feature_registry import feature_names
from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider
from cosmu.data.sources.osint_adsb import TRANSFORM_VERSION, AdsbDataSource
from cosmu.data.sources.registry import DataSource, DataSourceRegistry, SourceFeature, default_source_registry

_START = datetime(2024, 1, 1, tzinfo=UTC)


def _funding(n: int = 10) -> list[AltDataPoint]:
    return [AltDataPoint(ts=_START + timedelta(days=i), available_at=_START + timedelta(days=i), value=float(i)) for i in range(n)]


def test_registry_discovers_sources_by_name():
    alt = FixtureAltDataProvider({("BTCUSDT", "funding_rate"): _funding()})
    reg = default_source_registry(alt_provider=alt, include_osint=True)
    names = reg.names()
    assert "funding_rate" in names
    assert "osint_air_activity" in names
    catalog = reg.discover()
    by_name = {c["name"]: c for c in catalog}
    assert by_name["osint_air_activity"]["low_confidence"] is True
    assert by_name["funding_rate"]["low_confidence"] is False
    # every registered source satisfies the typed protocol
    for name in names:
        assert isinstance(reg.get(name), DataSource)


def test_registry_point_in_time_query_no_lookahead():
    alt = FixtureAltDataProvider({("BTCUSDT", "funding_rate"): _funding()})
    reg = default_source_registry(alt_provider=alt, include_osint=False)
    # as-of mid-series → the latest value whose availability <= as_of (day 5), never a future revision
    f = reg.query("funding_rate", "BTCUSDT", _START + timedelta(days=5, hours=1))
    assert isinstance(f, SourceFeature)
    assert f.value == 5.0
    assert f.available_at is not None and f.available_at <= _START + timedelta(days=5, hours=1)
    # before any data is knowable → None (no look-ahead into the future)
    assert reg.query("funding_rate", "BTCUSDT", _START - timedelta(days=1)).value is None


def test_adsb_source_parse_availability_and_low_confidence():
    src = AdsbDataSource(offline=True)
    # parse: 5 aircraft inside the US bbox (the one over France is excluded)
    assert src.parse_count() == 5
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    f = src.query("MARKET", as_of)
    assert f.value == 5.0
    # availability == observation time for a live snapshot (point-in-time, no look-ahead)
    assert f.available_at == as_of == f.as_of
    assert f.low_confidence is True
    assert f.confidence < 0.5
    assert f.transform_version == TRANSFORM_VERSION
    assert "OSINT" in f.prior or "OOS" in f.prior


def test_adsb_registered_and_in_feature_vocabulary():
    reg = DataSourceRegistry()
    reg.register(AdsbDataSource(offline=True))
    assert reg.discover()[0]["kind"] == "osint"
    # the new feature is in the named feature registry the lab agent references
    assert "osint_air_activity" in feature_names()
