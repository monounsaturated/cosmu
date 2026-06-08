"""Stablecoin FLOWS DataSource — offline, deterministic, no network, no key.

Verified invariants:
  1. PIT contract: available_at == ts + 1 day (daily aggregate finalized after the UTC day closes), not ts.
  2. No look-ahead: points whose available_at > as_of are excluded.
  3. Net-flow honesty: value == total(T) - total(T-1); a flow point is ABSENT across a missing day (no
     delta invented across a gap); sign is preserved (mints positive, redemptions negative).
  4. ETH-share: value == eth(T)/all(T), clamped to [0,1]; absent when either side is missing.
  5. Gap honesty: a missing / non-positive total is dropped (absent, never zero-filled).
  6. API / shape failure degrades to None (never raises).
  7. low_confidence is True (confidence < 0.5); transform_version is pinned; name == metric.
  8. DataSource protocol satisfied and registerable; unknown metric raises at construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.stablecoin_flows import (
    STABLECOIN_FLOW_METRICS,
    TRANSFORM_VERSION,
    StablecoinFlowsSource,
    _daily_totals,
    _extract_total_circulating,
    _parse_eth_share,
    _parse_net_flow,
    make_stablecoin_flow_sources,
)

_BASE = datetime(2024, 6, 1, tzinfo=UTC)  # arbitrary reference observation day (midnight UTC)


def _all_row(day: datetime, peg_usd: float) -> dict:
    """One /stablecoincharts/all row: nested totalCirculatingUSD dict (DefiLlama's real shape).

    Uses a noon-UTC unix stamp to exercise the midnight-normalization in the parser."""
    stamp = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return {"date": str(int(stamp.timestamp())), "totalCirculatingUSD": {"peggedUSD": peg_usd}}


def _all_payload(totals: list[float], start: datetime = _BASE) -> list[dict]:
    return [_all_row(start + timedelta(days=i), v) for i, v in enumerate(totals)]


# ---------------------------------------------------------------------------
# _extract_total_circulating + _daily_totals
# ---------------------------------------------------------------------------

def test_extract_total_circulating_nested_dict_sums():
    row = {"totalCirculatingUSD": {"peggedUSD": 100.0, "peggedEUR": 25.0}}
    assert _extract_total_circulating(row) == pytest.approx(125.0)


def test_extract_total_circulating_flat_and_fallback():
    assert _extract_total_circulating({"totalCirculatingUSD": 50.0}) == pytest.approx(50.0)
    assert _extract_total_circulating({"totalCirculating": {"peggedUSD": 7.0}}) == pytest.approx(7.0)


def test_extract_total_circulating_missing_or_nonpositive_is_none():
    assert _extract_total_circulating({}) is None
    assert _extract_total_circulating({"totalCirculatingUSD": {"peggedUSD": 0.0}}) is None
    assert _extract_total_circulating({"totalCirculatingUSD": -5.0}) is None


def test_daily_totals_normalizes_to_midnight_and_sorts():
    payload = _all_payload([10.0, 11.0, 12.0])
    pairs = _daily_totals(payload)
    assert [ts for ts, _ in pairs] == [_BASE, _BASE + timedelta(days=1), _BASE + timedelta(days=2)]
    for ts, _ in pairs:
        assert ts.hour == 0 and ts.minute == 0 and ts.second == 0


# ---------------------------------------------------------------------------
# _parse_net_flow
# ---------------------------------------------------------------------------

def test_net_flow_is_signed_day_over_day_delta():
    payload = _all_payload([100.0, 130.0, 120.0])  # +30 mint, -10 redeem
    pts = _parse_net_flow(payload)
    assert len(pts) == 2  # day0 has no predecessor → no flow point
    assert pts[0].ts == _BASE + timedelta(days=1)
    assert pts[0].value == pytest.approx(30.0)   # mint positive
    assert pts[1].value == pytest.approx(-10.0)  # redemption negative


def test_net_flow_available_at_is_ts_plus_one():
    pts = _parse_net_flow(_all_payload([100.0, 110.0]))
    assert pts[0].available_at == pts[0].ts + timedelta(days=1)


def test_net_flow_absent_across_a_gap():
    # days 0,1 present then a gap (skip day2) then day3 present → no flow point bridges the gap
    payload = _all_payload([100.0, 110.0]) + _all_payload([130.0], start=_BASE + timedelta(days=3))
    pts = _parse_net_flow(payload)
    # only the day0->day1 delta survives; day3 has no day2 predecessor
    assert len(pts) == 1
    assert pts[0].ts == _BASE + timedelta(days=1)


def test_net_flow_empty_or_malformed_payload():
    assert _parse_net_flow([]) == []
    assert _parse_net_flow("nonsense") == []
    assert _parse_net_flow([{"date": None}]) == []


# ---------------------------------------------------------------------------
# _parse_eth_share
# ---------------------------------------------------------------------------

def test_eth_share_is_fraction_clamped():
    all_p = _all_payload([100.0, 200.0])
    eth_p = _all_payload([40.0, 100.0])
    pts = _parse_eth_share(all_p, eth_p)
    assert len(pts) == 2
    assert pts[0].value == pytest.approx(0.40)
    assert pts[1].value == pytest.approx(0.50)
    assert pts[0].available_at == pts[0].ts + timedelta(days=1)


def test_eth_share_absent_when_either_side_missing():
    all_p = _all_payload([100.0, 200.0])
    eth_p = _all_payload([40.0])  # only day0 on the ETH side
    pts = _parse_eth_share(all_p, eth_p)
    assert len(pts) == 1
    assert pts[0].ts == _BASE


def test_eth_share_clamped_to_unit_interval():
    all_p = _all_payload([100.0])
    eth_p = _all_payload([150.0])  # eth > all (bad data) → clamp to 1.0
    pts = _parse_eth_share(all_p, eth_p)
    assert pts[0].value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# query() PIT behavior
# ---------------------------------------------------------------------------

def _net_flow_source(totals: list[float]) -> StablecoinFlowsSource:
    payload = _all_payload(totals)

    def _offline(url: str) -> list[dict]:  # noqa: ARG001
        return payload

    return StablecoinFlowsSource(metric="stablecoin_net_flow_usd", _fetcher=_offline)


def test_query_returns_latest_knowable_flow():
    src = _net_flow_source([100.0, 130.0, 120.0, 140.0])
    # flow points: day1(+30, avail day2), day2(-10, avail day3), day3(+20, avail day4)
    as_of = _BASE + timedelta(days=3, hours=1)  # day3 flow not yet available (avail day4)
    f = src.query("BTCUSDT", as_of)
    assert f.value == pytest.approx(-10.0)  # latest knowable = day2 flow
    assert f.available_at is not None and f.available_at <= as_of
    assert f.scope == "MARKET"


def test_query_no_lookahead_before_any_data():
    src = _net_flow_source([100.0, 130.0])
    # earliest flow point is day1, available day2 → as_of=_BASE knows nothing
    f = src.query("BTCUSDT", _BASE)
    assert f.value is None
    assert f.available_at is None


def test_query_eth_share_market_wide():
    all_p = _all_payload([100.0, 200.0])
    eth_p = _all_payload([40.0, 100.0])

    def _offline(url: str) -> list[dict]:
        return eth_p if url.endswith("Ethereum") else all_p

    src = StablecoinFlowsSource(metric="stablecoin_eth_share", _fetcher=_offline)
    f = src.query("ETHUSDT", _BASE + timedelta(days=2))
    assert f.value == pytest.approx(0.50)  # latest knowable = day1 share
    assert f.scope == "MARKET"


def test_api_failure_returns_none_not_raises():
    def _bad(_url: str) -> list:
        raise RuntimeError("network down")

    src = StablecoinFlowsSource(metric="stablecoin_net_flow_usd", _fetcher=_bad)
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None


# ---------------------------------------------------------------------------
# metadata + protocol
# ---------------------------------------------------------------------------

def test_unknown_metric_raises_at_construction():
    with pytest.raises(ValueError, match="unknown stablecoin-flow metric"):
        StablecoinFlowsSource(metric="bogus")


def test_name_equals_metric():
    for metric in STABLECOIN_FLOW_METRICS:
        assert StablecoinFlowsSource(metric=metric).name == metric


def test_low_confidence_flag_and_transform_pinned():
    src = StablecoinFlowsSource()
    assert src.confidence < 0.5
    assert src.low_confidence is True
    assert src.transform_version == TRANSFORM_VERSION


def test_make_sources_returns_one_per_metric():
    names = {s.name for s in make_stablecoin_flow_sources()}
    assert names == set(STABLECOIN_FLOW_METRICS)


def test_satisfies_datasource_protocol_and_registerable():
    from cosmu.data.sources.registry import DataSource, DataSourceRegistry

    reg = DataSourceRegistry()
    for src in make_stablecoin_flow_sources():
        assert isinstance(src, DataSource)
        reg.register(src)
    for metric in STABLECOIN_FLOW_METRICS:
        assert metric in reg.names()
    catalog = reg.discover()
    entry = next(c for c in catalog if c["name"] == "stablecoin_net_flow_usd")
    assert entry["low_confidence"] is True
    assert entry["kind"] == "macro"
