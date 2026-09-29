"""Macro-liquidity (FRED keyless) DataSource — offline, deterministic, no network, no key.

Verified invariants:
  1. PIT contract: available_at == ts + 8 days (conservative H.4.1 publication-lag floor), not ts.
  2. No look-ahead: points whose available_at > as_of are excluded.
  3. net_liquidity == WALCL(T) - TGA(T); a date is ABSENT whenever either series lacks it (no fabricated
     difference).
  4. Gap honesty: a "." / missing value is dropped (absent, never zero-filled).
  5. CSV header row and malformed rows are skipped.
  6. API / shape failure degrades to None (never raises).
  7. low_confidence is True (confidence < 0.5); transform_version is pinned; name == metric.
  8. DataSource protocol satisfied and registerable; unknown metric raises at construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.etf_flows import (
    ETF_FLOW_METRICS,
    TRANSFORM_VERSION,
    EtfFlowsSource,
    _net_liquidity_points,
    _parse_fredgraph_csv,
    _points_from_map,
    make_etf_flow_sources,
)

_BASE = datetime(2024, 6, 5, tzinfo=UTC)  # a Wednesday-like reference date
_LAG = timedelta(days=8)


def _csv(series_id: str, rows: list[tuple[str, str]]) -> str:
    """Build a fredgraph.csv body: header `observation_date,<id>` then date,value rows."""
    lines = [f"observation_date,{series_id}"]
    lines += [f"{d},{v}" for d, v in rows]
    return "\n".join(lines)


def _walcl_csv(values: list[float], start: datetime = _BASE) -> str:
    rows = [((start + timedelta(days=7 * i)).date().isoformat(), str(v)) for i, v in enumerate(values)]
    return _csv("WALCL", rows)


def _tga_csv(values: list[float], start: datetime = _BASE) -> str:
    rows = [((start + timedelta(days=7 * i)).date().isoformat(), str(v)) for i, v in enumerate(values)]
    return _csv("WTREGEN", rows)


# ---------------------------------------------------------------------------
# _parse_fredgraph_csv
# ---------------------------------------------------------------------------

def test_parse_csv_basic_and_midnight_normalization():
    text = _csv("WALCL", [("2024-06-05", "7000000"), ("2024-06-12", "7010000")])
    m = _parse_fredgraph_csv(text, "WALCL")
    assert m[datetime(2024, 6, 5, tzinfo=UTC)] == pytest.approx(7000000.0)
    assert m[datetime(2024, 6, 12, tzinfo=UTC)] == pytest.approx(7010000.0)
    for ts in m:
        assert ts.hour == 0 and ts.minute == 0 and ts.tzinfo == UTC


def test_parse_csv_skips_header_and_missing_values():
    text = _csv("WALCL", [("2024-06-05", "."), ("2024-06-12", ""), ("2024-06-19", "7020000")])
    m = _parse_fredgraph_csv(text, "WALCL")
    assert list(m.keys()) == [datetime(2024, 6, 19, tzinfo=UTC)]  # only the real value survives


def test_parse_csv_non_string_or_garbage_is_empty():
    assert _parse_fredgraph_csv(None, "WALCL") == {}
    assert _parse_fredgraph_csv(123, "WALCL") == {}
    assert _parse_fredgraph_csv("garbage,line,with,no,date", "WALCL") == {}


# ---------------------------------------------------------------------------
# _points_from_map + PIT lag
# ---------------------------------------------------------------------------

def test_points_from_map_applies_eight_day_lag_and_sorts():
    m = {
        datetime(2024, 6, 12, tzinfo=UTC): 2.0,
        datetime(2024, 6, 5, tzinfo=UTC): 1.0,
    }
    pts = _points_from_map(m)
    assert [p.ts for p in pts] == [datetime(2024, 6, 5, tzinfo=UTC), datetime(2024, 6, 12, tzinfo=UTC)]
    for p in pts:
        assert p.available_at == p.ts + _LAG
        assert p.available_at > p.ts  # lag is present, not zero


# ---------------------------------------------------------------------------
# _net_liquidity_points
# ---------------------------------------------------------------------------

def test_net_liquidity_is_walcl_minus_tga():
    walcl = {_BASE: 7000000.0, _BASE + timedelta(days=7): 7010000.0}
    tga = {_BASE: 500000.0, _BASE + timedelta(days=7): 600000.0}
    pts = _net_liquidity_points(walcl, tga)
    assert len(pts) == 2
    assert pts[0].value == pytest.approx(6500000.0)
    assert pts[1].value == pytest.approx(6410000.0)
    assert pts[0].available_at == pts[0].ts + _LAG


def test_net_liquidity_absent_when_tga_missing():
    walcl = {_BASE: 7000000.0, _BASE + timedelta(days=7): 7010000.0}
    tga = {_BASE: 500000.0}  # second week missing on the TGA side
    pts = _net_liquidity_points(walcl, tga)
    assert len(pts) == 1
    assert pts[0].ts == _BASE


# ---------------------------------------------------------------------------
# query() PIT behavior
# ---------------------------------------------------------------------------

def _balance_source(values: list[float]) -> EtfFlowsSource:
    csv = _walcl_csv(values)

    def _offline(url: str) -> str:  # noqa: ARG001
        return csv

    return EtfFlowsSource(metric="fed_balance_sheet_usd", _fetcher=_offline)


def test_query_returns_latest_knowable_value():
    src = _balance_source([7000000.0, 7010000.0, 7020000.0])
    # week2 ts = _BASE + 14d, available_at = _BASE + 22d. Pick as_of so only week0+week1 are knowable.
    as_of = _BASE + timedelta(days=7) + _LAG  # == week1 available exactly; week2 not yet
    f = src.query("BTCUSDT", as_of)
    assert f.value == pytest.approx(7010000.0)  # week1 is the latest knowable
    assert f.available_at is not None and f.available_at <= as_of
    assert f.scope == "MARKET"


def test_query_no_lookahead_before_any_data():
    src = _balance_source([7000000.0])
    f = src.query("BTCUSDT", _BASE)  # week0 available only at _BASE + 8d
    assert f.value is None
    assert f.available_at is None


def test_query_net_liquidity_market_wide():
    walcl = _walcl_csv([7000000.0, 7010000.0])
    tga = _tga_csv([500000.0, 600000.0])

    def _offline(url: str) -> str:
        return tga if "WTREGEN" in url else walcl

    src = EtfFlowsSource(metric="net_liquidity_usd", _fetcher=_offline)
    as_of = _BASE + timedelta(days=7) + _LAG
    f = src.query("ETHUSDT", as_of)
    assert f.value == pytest.approx(6410000.0)  # week1 net liquidity
    assert f.scope == "MARKET"


def test_api_failure_returns_none_not_raises():
    def _bad(_url: str) -> str:
        raise RuntimeError("network down")

    src = EtfFlowsSource(metric="fed_balance_sheet_usd", _fetcher=_bad)
    f = src.query("BTCUSDT", _BASE + timedelta(days=365))
    assert f.value is None


# ---------------------------------------------------------------------------
# metadata + protocol
# ---------------------------------------------------------------------------

def test_unknown_metric_raises_at_construction():
    with pytest.raises(ValueError, match="unknown macro-liquidity metric"):
        EtfFlowsSource(metric="bogus")


def test_name_equals_metric():
    for metric in ETF_FLOW_METRICS:
        assert EtfFlowsSource(metric=metric).name == metric


def test_low_confidence_flag_and_transform_pinned():
    src = EtfFlowsSource()
    assert src.confidence < 0.5
    assert src.low_confidence is True
    assert src.transform_version == TRANSFORM_VERSION


def test_make_sources_returns_one_per_metric():
    names = {s.name for s in make_etf_flow_sources()}
    assert names == set(ETF_FLOW_METRICS)


def test_satisfies_datasource_protocol_and_registerable():
    from cosmu.data.sources.registry import DataSource, DataSourceRegistry

    reg = DataSourceRegistry()
    for src in make_etf_flow_sources():
        assert isinstance(src, DataSource)
        reg.register(src)
    for metric in ETF_FLOW_METRICS:
        assert metric in reg.names()
    catalog = reg.discover()
    entry = next(c for c in catalog if c["name"] == "net_liquidity_usd")
    assert entry["low_confidence"] is True
    assert entry["kind"] == "macro"
