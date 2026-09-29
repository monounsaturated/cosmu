"""blockchain.com on-chain DataSource — offline, deterministic, no network.

Verified invariants:
  1. PIT contract: available_at == ts + 1 day (the conservative ≥1-day publication lag), not ts.
  2. No look-ahead: points whose available_at > as_of are excluded.
  3. Gap honesty: a missing day is absent, never zero-filled; before-any-data → value=None.
  4. Each metric maps to the right blockchain.com chart slug; unknown metric → empty series.
  5. _parse_response normalizes the unix-second x to midnight UTC and skips malformed points.
  6. API failure degrades to None (never raises).
  7. low_confidence is True (confidence < 0.5); transform_version is pinned.
  8. DataSource protocol satisfied and registerable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.onchain_blockchain import (
    METRIC_CHART_MAP,
    TRANSFORM_VERSION,
    OnchainBlockchainSource,
    _chart_for_metric,
    _parse_response,
    make_onchain_blockchain_sources,
)

_BASE = datetime(2024, 6, 1, tzinfo=UTC)  # arbitrary reference observation day


def _make_response(days: int = 10, base_val: float = 5.0e20) -> dict:
    """Fabricate a blockchain.com charts response: {"values": [{"x": unix, "y": val}, ...]}.

    Day i carries a midday-UTC unix stamp (12:00) to exercise the midnight-normalization in the parser."""
    values = []
    for i in range(days):
        day = _BASE + timedelta(days=i, hours=12)  # noon UTC → must normalize to midnight of that day
        values.append({"x": int(day.timestamp()), "y": base_val + i * 1.0e19})
    return {"values": values}


def _source(metric: str = "btc_hashrate", days: int = 10) -> OnchainBlockchainSource:
    """An OnchainBlockchainSource wired to an offline fixture fetcher (zero network)."""
    fixture = _make_response(days=days)

    def _offline(url: str) -> dict:  # noqa: ARG001
        return fixture

    return OnchainBlockchainSource(metric=metric, _fetcher=_offline)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_pit_availability_and_midnight_normalization():
    """available_at == ts + 1 day, and ts is normalized to midnight UTC of the observation day."""
    payload = _make_response(days=3)
    pts = _parse_response(payload)
    assert len(pts) == 3
    for pt in pts:
        # ts is midnight (hour/min/sec all zero) despite the noon-UTC x in the fixture
        assert pt.ts.hour == 0 and pt.ts.minute == 0 and pt.ts.second == 0
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_parse_response_ascending_order():
    pts = _parse_response(_make_response(days=5))
    tss = [p.ts for p in pts]
    assert tss == sorted(tss)


def test_parse_response_skips_malformed_points():
    payload = {
        "values": [
            {"x": int((_BASE).timestamp()), "y": 1.0},
            {"x": int((_BASE + timedelta(days=1)).timestamp())},  # missing y
            {"y": 2.0},  # missing x
            {"x": int((_BASE + timedelta(days=2)).timestamp()), "y": 3.0},
        ]
    }
    pts = _parse_response(payload)
    assert len(pts) == 2  # only the two complete points survive (gaps absent, not zero)


def test_parse_response_empty_payload():
    assert _parse_response({}) == []
    assert _parse_response({"values": []}) == []


# ---------------------------------------------------------------------------
# metric → chart resolution
# ---------------------------------------------------------------------------

def test_chart_for_known_metrics():
    assert _chart_for_metric("btc_hashrate") == "hash-rate"
    assert _chart_for_metric("btc_tx_count") == "n-transactions"
    assert _chart_for_metric("btc_mempool_size") == "mempool-size"
    assert _chart_for_metric("btc_active_addresses") == "n-unique-addresses"


def test_chart_for_unknown_metric_is_none():
    assert _chart_for_metric("not_a_metric") is None


def test_all_metrics_have_charts():
    for metric in METRIC_CHART_MAP:
        assert _chart_for_metric(metric)


# ---------------------------------------------------------------------------
# query() PIT behavior
# ---------------------------------------------------------------------------

def test_query_returns_latest_knowable_value():
    src = _source("btc_hashrate", days=10)
    # as_of = day5 + 1h → last available point is day 4 (available_at = day5 midnight)
    as_of = _BASE + timedelta(days=5, hours=1)
    f = src.query("BTCUSDT", as_of)
    assert f.value is not None
    # day 4: base_val + 4 * 1e19
    assert f.value == pytest.approx(5.0e20 + 4 * 1.0e19)
    assert f.available_at is not None and f.available_at <= as_of
    assert f.scope == "MARKET"  # market-wide; scope arg is ignored


def test_query_no_lookahead_before_any_data():
    src = _source("btc_hashrate", days=10)
    # as_of == _BASE: day-0 available_at = _BASE + 1d > as_of → nothing knowable yet
    f = src.query("BTCUSDT", _BASE)
    assert f.value is None
    assert f.available_at is None


def test_query_available_at_is_ts_plus_one():
    src = _source("btc_tx_count", days=10)
    as_of = _BASE + timedelta(days=6)
    f = src.query("BTCUSDT", as_of)
    assert f.available_at is not None
    # winning point is day 5 (ts=_BASE+5d), available_at=_BASE+6d
    day5_ts = _BASE + timedelta(days=5)
    assert f.available_at == day5_ts + timedelta(days=1)
    assert f.available_at > day5_ts  # 1-day lag is present, not zero


def test_unknown_metric_returns_none_not_raises():
    src = _source("btc_hashrate", days=5)
    src.metric = "bogus_metric"  # force an unknown chart
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None
    assert f.available_at is None


def test_api_failure_returns_none_not_raises():
    def _bad(_url: str) -> dict:
        raise RuntimeError("network down")

    src = OnchainBlockchainSource(metric="btc_hashrate", _fetcher=_bad)
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None


# ---------------------------------------------------------------------------
# metadata + protocol
# ---------------------------------------------------------------------------

def test_name_equals_metric():
    """The feature key (name) must equal the metric so the registry stays consistent."""
    for metric in METRIC_CHART_MAP:
        src = OnchainBlockchainSource(metric=metric)
        assert src.name == metric


def test_low_confidence_flag():
    src = OnchainBlockchainSource()
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_transform_version_pinned():
    assert OnchainBlockchainSource().transform_version == TRANSFORM_VERSION


def test_source_feature_fields_populated():
    src = _source("btc_active_addresses", days=10)
    as_of = _BASE + timedelta(days=5)
    f = src.query("ETHUSDT", as_of)
    assert f.name == "btc_active_addresses"
    assert f.scope == "MARKET"
    assert f.as_of == as_of
    assert f.confidence == src.confidence
    assert f.transform_version == TRANSFORM_VERSION
    assert f.low_confidence is True


def test_make_sources_returns_one_per_metric():
    srcs = make_onchain_blockchain_sources()
    names = {s.name for s in srcs}
    assert names == set(METRIC_CHART_MAP.keys())


def test_satisfies_datasource_protocol_and_registerable():
    from cosmu.data.sources.registry import DataSource, DataSourceRegistry

    reg = DataSourceRegistry()
    for src in make_onchain_blockchain_sources():
        assert isinstance(src, DataSource)
        reg.register(src)
    for metric in METRIC_CHART_MAP:
        assert metric in reg.names()
    catalog = reg.discover()
    entry = next(c for c in catalog if c["name"] == "btc_hashrate")
    assert entry["low_confidence"] is True
    assert entry["kind"] == "macro"
