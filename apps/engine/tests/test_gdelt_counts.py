"""GDELT 2.0 news-volume COUNTS DataSource — offline, deterministic, no network.

Verified invariants:
  1. PIT contract: available_at == ts + 1 day (conservative ≥1-day lag for a complete UTC day), not ts.
  2. No look-ahead: points whose available_at > as_of are excluded.
  3. Gap honesty: a missing day is absent, never zero-filled; before-any-data → value=None.
  4. Symbol → GDELT query resolution (exact map + base-asset fallback); unknown → None (never raises).
  5. _parse_response normalizes GDELT date stamps to midnight UTC and skips malformed points.
  6. API failure degrades to None (never raises).
  7. low_confidence is True (confidence < 0.5); transform_version is pinned.
  8. DataSource protocol satisfied and registerable. COUNTS ONLY — value is the article count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.gdelt_counts import (
    TOPIC_MAP,
    TRANSFORM_VERSION,
    GdeltCountsSource,
    _parse_response,
    _query_for_symbol,
)

_BASE = datetime(2024, 6, 1, tzinfo=UTC)


def _make_response(days: int = 10, base_count: int = 100) -> dict:
    """Fabricate a GDELT DOC 2.0 timelinevolraw response.

    Shape: {"timeline": [{"series": "...", "data": [{"date": "YYYYMMDDT000000Z", "value": N}]}]}.
    Counts increase monotonically so tests can assert ordering / latest-selection."""
    data = []
    for i in range(days):
        day = _BASE + timedelta(days=i)
        data.append({"date": day.strftime("%Y%m%dT000000Z"), "value": base_count + i * 10})
    return {"timeline": [{"series": "Volume Raw", "data": data}]}


def _source(metric: str = "gdelt_news_volume", days: int = 10) -> GdeltCountsSource:
    """A GdeltCountsSource wired to an offline fixture fetcher (zero network)."""
    fixture = _make_response(days=days)

    def _offline(url: str) -> dict:  # noqa: ARG001
        return fixture

    return GdeltCountsSource(metric=metric, _fetcher=_offline)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def test_parse_response_pit_availability():
    pts = _parse_response(_make_response(days=3))
    assert len(pts) == 3
    for pt in pts:
        assert pt.ts.hour == 0 and pt.ts.minute == 0  # normalized to midnight UTC
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_parse_response_ascending_order():
    pts = _parse_response(_make_response(days=5))
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)


def test_parse_response_value_is_count():
    """The value carried is the raw article COUNT (not a tone/score)."""
    pts = _parse_response(_make_response(days=3, base_count=250))
    assert pts[0].value == pytest.approx(250.0)
    assert pts[1].value == pytest.approx(260.0)


def test_parse_response_skips_malformed():
    payload = {
        "timeline": [
            {
                "data": [
                    {"date": "20240601T000000Z", "value": 5},
                    {"date": "20240602T000000Z"},  # missing value
                    {"value": 7},                   # missing date
                    {"date": "garbage", "value": 9},  # unparseable date
                    {"date": "20240603T000000Z", "value": 11},
                ]
            }
        ]
    }
    pts = _parse_response(payload)
    assert len(pts) == 2  # only the two valid points survive — gaps absent, not zero


def test_parse_response_empty():
    assert _parse_response({}) == []
    assert _parse_response({"timeline": []}) == []


def test_parse_response_handles_z_and_plain_stamps():
    """Both '20240601T000000Z' and '20240601000000' (no T/Z) parse to the same midnight-UTC day."""
    payload = {
        "timeline": [
            {"data": [
                {"date": "20240601T000000Z", "value": 1},
                {"date": "20240602000000", "value": 2},
            ]}
        ]
    }
    pts = _parse_response(payload)
    assert len(pts) == 2
    assert pts[0].ts == datetime(2024, 6, 1, tzinfo=UTC)
    assert pts[1].ts == datetime(2024, 6, 2, tzinfo=UTC)


# ---------------------------------------------------------------------------
# symbol → query resolution
# ---------------------------------------------------------------------------

def test_query_for_known_symbol():
    assert _query_for_symbol("BTCUSDT") == '"bitcoin"'
    assert _query_for_symbol("ETHUSDT") == '"ethereum"'
    assert _query_for_symbol("MARKET") is not None


def test_query_for_base_asset_fallback():
    """SOLBTC (not in TOPIC_MAP) → strip 'BTC' → 'SOL' → fallback query."""
    assert _query_for_symbol("SOLBTC") == '"solana"'


def test_query_for_unknown_symbol_is_none():
    assert _query_for_symbol("UNKNOWNXXX") is None


# ---------------------------------------------------------------------------
# query() PIT behavior
# ---------------------------------------------------------------------------

def test_query_returns_latest_knowable_count():
    src = _source(days=10)
    as_of = _BASE + timedelta(days=5, hours=1)  # last available = day 4
    f = src.query("BTCUSDT", as_of)
    assert f.value is not None
    assert f.value == pytest.approx(100 + 4 * 10)  # day 4 count
    assert f.available_at is not None and f.available_at <= as_of


def test_query_no_lookahead_before_any_data():
    src = _source(days=10)
    f = src.query("BTCUSDT", _BASE)  # day-0 available_at = _BASE+1d > as_of
    assert f.value is None
    assert f.available_at is None


def test_query_available_at_is_ts_plus_one():
    src = _source(days=10)
    as_of = _BASE + timedelta(days=6)
    f = src.query("BTCUSDT", as_of)
    day5_ts = _BASE + timedelta(days=5)
    assert f.available_at == day5_ts + timedelta(days=1)
    assert f.available_at > day5_ts


def test_unknown_symbol_returns_none_not_raises():
    src = _source(days=5)
    f = src.query("UNKNOWNTOKEN999", _BASE + timedelta(days=10))
    assert f.value is None
    assert f.available_at is None


def test_api_failure_returns_none_not_raises():
    def _bad(_url: str) -> dict:
        raise RuntimeError("network down")

    src = GdeltCountsSource(_fetcher=_bad)
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None


# ---------------------------------------------------------------------------
# metadata + protocol
# ---------------------------------------------------------------------------

def test_low_confidence_flag():
    src = GdeltCountsSource()
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_transform_version_pinned():
    assert GdeltCountsSource().transform_version == TRANSFORM_VERSION


def test_name_and_kind():
    src = GdeltCountsSource()
    assert src.name == "gdelt_news_volume"
    assert "_" in src.name and " " not in src.name  # snake_case feature key
    assert src.kind == "sentiment"


def test_source_feature_fields_populated():
    src = _source(days=10)
    as_of = _BASE + timedelta(days=5)
    f = src.query("BTCUSDT", as_of)
    assert f.name == "gdelt_news_volume"
    assert f.scope == "BTCUSDT"
    assert f.as_of == as_of
    assert f.confidence == src.confidence
    assert f.transform_version == TRANSFORM_VERSION
    assert f.low_confidence is True


def test_topic_map_nonempty():
    assert TOPIC_MAP.get("BTCUSDT")


def test_satisfies_datasource_protocol_and_registerable():
    from cosmu.data.sources.registry import DataSource, DataSourceRegistry

    src = GdeltCountsSource()
    assert isinstance(src, DataSource)
    reg = DataSourceRegistry()
    reg.register(src)
    assert "gdelt_news_volume" in reg.names()
    entry = next(c for c in reg.discover() if c["name"] == "gdelt_news_volume")
    assert entry["low_confidence"] is True
    assert entry["kind"] == "sentiment"
