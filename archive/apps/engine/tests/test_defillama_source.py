"""DefiLlama named-DataSource adapter — offline, deterministic, no network.

Tests cover:
  - PIT contract: available_at == ts + 1 day (not ts)
  - No look-ahead: points with available_at > as_of are excluded
  - No fabrication: gaps / non-positive values are absent, never zero
  - query() returns None when nothing is knowable yet (before any data)
  - stablecoin_mcap: nested totalCirculatingUSD dict summed correctly; flat numeric tolerated
  - Network failure → None-valued SourceFeature (never raises)
  - DataSource protocol satisfied (name, kind, metric, prior, transform_version, confidence)
  - low_confidence is True (confidence < 0.5)
  - make_defillama_sources() builds one source per owned metric
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.defillama import (
    DEFILLAMA_METRICS,
    TRANSFORM_VERSION,
    DefiLlamaSource,
    _extract_total_circulating,
    _parse_stablecoin_mcap,
    _parse_tvl,
    make_defillama_sources,
)

_BASE = datetime(2024, 6, 1, tzinfo=UTC)  # arbitrary reference date (midnight UTC)


def _tvl_payload(days: int = 10, base_tvl: float = 50_000_000_000.0) -> list[dict]:
    """Fabricate a /v2/historicalChainTvl response: [{"date": unix_s, "tvl": usd}, ...] over `days` days."""
    out = []
    for i in range(days):
        day = _BASE + timedelta(days=i)
        out.append({"date": int(day.timestamp()), "tvl": base_tvl + i * 1_000_000_000.0})
    return out


def _stablecoin_payload(days: int = 10, base_mcap: float = 130_000_000_000.0) -> list[dict]:
    """Fabricate a /stablecoincharts/all response with the nested totalCirculatingUSD dict shape."""
    out = []
    for i in range(days):
        day = _BASE + timedelta(days=i)
        total = base_mcap + i * 500_000_000.0
        # Split across two peg types so the sum-of-values path is exercised.
        out.append({
            "date": str(int(day.timestamp())),
            "totalCirculatingUSD": {"peggedUSD": total * 0.9, "peggedEUR": total * 0.1},
        })
    return out


def _source(metric: str, payload) -> DefiLlamaSource:
    """A DefiLlamaSource wired to an offline fixture fetcher (zero network)."""
    def _offline(url: str):  # noqa: ARG001
        return payload
    return DefiLlamaSource(metric=metric, _fetcher=_offline)


# --------------------------------------------------------------------------- _parse_tvl


def test_parse_tvl_pit_availability():
    """available_at must be exactly ts + 1 day (a daily aggregate is finalized after the day closes)."""
    pts = _parse_tvl(_tvl_payload(days=3))
    assert len(pts) == 3
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_parse_tvl_drops_nonpositive_and_missing():
    """Non-positive / missing tvl rows are absent (never zero-fabricated)."""
    payload = [
        {"date": int(_BASE.timestamp()), "tvl": 1.0},
        {"date": int((_BASE + timedelta(days=1)).timestamp()), "tvl": 0.0},      # zero → absent
        {"date": int((_BASE + timedelta(days=2)).timestamp())},                  # missing tvl → absent
        {"date": int((_BASE + timedelta(days=3)).timestamp()), "tvl": -5.0},     # negative → absent
        {"date": int((_BASE + timedelta(days=4)).timestamp()), "tvl": 2.0},
    ]
    pts = _parse_tvl(payload)
    assert len(pts) == 2


def test_parse_tvl_non_list_payload():
    """A non-list payload (e.g. an error dict) returns []."""
    assert _parse_tvl({"error": "rate limited"}) == []
    assert _parse_tvl(None) == []


# --------------------------------------------------------------------------- stablecoin mcap


def test_extract_total_circulating_sums_nested_dict():
    row = {"totalCirculatingUSD": {"peggedUSD": 100.0, "peggedEUR": 23.0}}
    assert _extract_total_circulating(row) == pytest.approx(123.0)


def test_extract_total_circulating_flat_numeric():
    assert _extract_total_circulating({"totalCirculatingUSD": 999.0}) == pytest.approx(999.0)


def test_extract_total_circulating_fallback_key():
    assert _extract_total_circulating({"totalCirculating": {"peggedUSD": 7.0}}) == pytest.approx(7.0)


def test_extract_total_circulating_absent():
    assert _extract_total_circulating({"date": 123}) is None


def test_parse_stablecoin_pit_availability():
    pts = _parse_stablecoin_mcap(_stablecoin_payload(days=4))
    assert len(pts) == 4
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_parse_stablecoin_sum_value():
    """The day's value equals the sum of the nested peg-type circulating values."""
    pts = _parse_stablecoin_mcap(_stablecoin_payload(days=1, base_mcap=200.0))
    assert len(pts) == 1
    # 200 * 0.9 + 200 * 0.1 == 200
    assert pts[0].value == pytest.approx(200.0)


# --------------------------------------------------------------------------- query (defi_tvl)


def test_tvl_query_latest_pit():
    """query() returns the latest tvl whose available_at <= as_of."""
    src = _source("defi_tvl", _tvl_payload(days=10))
    # day i has available_at = _BASE + (i+1)d. as_of = _BASE + 5d + 1h → last knowable is day 4.
    as_of = _BASE + timedelta(days=5, hours=1)
    f = src.query("MARKET", as_of)
    assert f.value == pytest.approx(50_000_000_000.0 + 4 * 1_000_000_000.0)
    assert f.available_at is not None and f.available_at <= as_of
    assert f.scope == "MARKET"


def test_tvl_no_lookahead_before_any_data():
    """At as_of = _BASE, day-0's available_at is _BASE + 1d → nothing knowable yet."""
    src = _source("defi_tvl", _tvl_payload(days=10))
    f = src.query("MARKET", _BASE)
    assert f.value is None
    assert f.available_at is None


# --------------------------------------------------------------------------- query (stablecoin_mcap)


def test_stablecoin_query_latest_pit():
    src = _source("stablecoin_mcap", _stablecoin_payload(days=6, base_mcap=100.0))
    as_of = _BASE + timedelta(days=4, hours=1)  # last knowable is day 3
    f = src.query("MARKET", as_of)
    assert f.value == pytest.approx(100.0 + 3 * 500_000_000.0)


# --------------------------------------------------------------------------- robustness


def test_network_failure_returns_none_not_raises():
    def _bad(_url: str):
        raise RuntimeError("network down")
    src = DefiLlamaSource(metric="defi_tvl", _fetcher=_bad)
    f = src.query("MARKET", _BASE + timedelta(days=10))
    assert f.value is None


def test_unknown_metric_raises_at_construction():
    with pytest.raises(ValueError, match="unknown DefiLlama metric"):
        DefiLlamaSource(metric="not_a_metric")


# --------------------------------------------------------------------------- protocol + metadata


def test_datasource_protocol_attributes():
    for metric in DEFILLAMA_METRICS:
        src = DefiLlamaSource(metric=metric)
        assert src.name == metric
        assert src.metric == metric
        assert src.kind == "macro"
        assert src.prior  # non-empty
        assert src.transform_version == TRANSFORM_VERSION
        assert 0.0 < src.confidence <= 1.0


def test_low_confidence_flag():
    src = DefiLlamaSource(metric="defi_tvl")
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_make_defillama_sources_covers_all_metrics():
    srcs = make_defillama_sources()
    assert {s.metric for s in srcs} == set(DEFILLAMA_METRICS)
    assert {s.name for s in srcs} == set(DEFILLAMA_METRICS)


def test_source_feature_fields_populated():
    src = _source("defi_tvl", _tvl_payload(days=10))
    as_of = _BASE + timedelta(days=5)
    f = src.query("MARKET", as_of)
    assert f.name == "defi_tvl"
    assert f.as_of == as_of
    assert f.confidence == src.confidence
    assert f.transform_version == TRANSFORM_VERSION
    assert f.low_confidence is True
