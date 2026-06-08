"""CoinGecko named-DataSource adapter — offline, deterministic, no network.

Tests cover:
  - PIT contract: per-coin daily available_at == ts + 1 day (bucket normalised to midnight UTC)
  - No look-ahead: points with available_at > as_of are excluded
  - No fabrication: null / non-positive values are absent, never zero
  - query() returns None when nothing is knowable yet (before any data)
  - cg_total_volume reads the total_volumes array; cg_market_cap reads market_caps
  - cg_btc_dominance: current snapshot from /global, available_at == fetch time
  - Unknown symbol returns None-valued SourceFeature (never raises)
  - Network failure → None-valued SourceFeature (never raises)
  - symbol → coin id resolution (exact + base-asset fallback + unknown)
  - DataSource protocol satisfied; low_confidence is True
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cosmu.data.sources.coingecko import (
    COIN_ID_MAP,
    COINGECKO_METRICS,
    TRANSFORM_VERSION,
    CoinGeckoSource,
    _coin_id_for_symbol,
    _parse_btc_dominance,
    _parse_market_chart,
    make_coingecko_sources,
)

_BASE = datetime(2024, 6, 1, tzinfo=UTC)  # midnight UTC reference


def _chart_payload(days: int = 10, base: float = 1_000_000_000.0) -> dict:
    """A market_chart response with both market_caps and total_volumes daily arrays."""
    caps, vols = [], []
    for i in range(days):
        day = _BASE + timedelta(days=i)
        ts_ms = int(day.timestamp() * 1000)
        caps.append([ts_ms, base + i * 10_000_000.0])
        vols.append([ts_ms, base / 10 + i * 1_000_000.0])
    return {"prices": [], "market_caps": caps, "total_volumes": vols}


def _global_payload(btc_pct: float = 52.5) -> dict:
    return {"data": {"market_cap_percentage": {"btc": btc_pct, "eth": 17.0}}}


def _source(metric: str, payload) -> CoinGeckoSource:
    def _offline(url: str):  # noqa: ARG001
        return payload
    return CoinGeckoSource(metric=metric, _fetcher=_offline)


# --------------------------------------------------------------------------- coin id resolution


def test_coin_id_known_symbol():
    assert _coin_id_for_symbol("BTCUSDT") == "bitcoin"
    assert _coin_id_for_symbol("ETHUSDT") == "ethereum"
    assert _coin_id_for_symbol("SOLUSDT") == "solana"


def test_coin_id_base_asset_fallback():
    """SOLBTC (not in COIN_ID_MAP) → strip BTC → SOL → fallback."""
    assert _coin_id_for_symbol("SOLBTC") == "solana"


def test_coin_id_unknown():
    assert _coin_id_for_symbol("NOSUCHCOINXX") is None


# --------------------------------------------------------------------------- _parse_market_chart


def test_parse_market_chart_pit_availability():
    """available_at == day midnight + 1 day; bucket ts normalised to midnight UTC."""
    pts = _parse_market_chart(_chart_payload(days=3), "market_caps")
    assert len(pts) == 3
    for pt in pts:
        assert pt.ts.hour == 0 and pt.ts.minute == 0
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_parse_market_chart_volume_key():
    pts = _parse_market_chart(_chart_payload(days=5, base=1_000_000_000.0), "total_volumes")
    assert len(pts) == 5
    # day 0 volume = base/10
    assert pts[0].value == pytest.approx(100_000_000.0)


def test_parse_market_chart_drops_null_and_nonpositive():
    payload = {"market_caps": [
        [int(_BASE.timestamp() * 1000), 5.0],
        [int((_BASE + timedelta(days=1)).timestamp() * 1000), None],   # null → absent
        [int((_BASE + timedelta(days=2)).timestamp() * 1000), 0.0],    # zero → absent
        [int((_BASE + timedelta(days=3)).timestamp() * 1000), 9.0],
    ]}
    pts = _parse_market_chart(payload, "market_caps")
    assert len(pts) == 2


def test_parse_market_chart_non_dict():
    assert _parse_market_chart([1, 2, 3], "market_caps") == []
    assert _parse_market_chart(None, "market_caps") == []


# --------------------------------------------------------------------------- query (per-coin)


def test_market_cap_query_latest_pit():
    src = _source("cg_market_cap", _chart_payload(days=10, base=1_000_000_000.0))
    as_of = _BASE + timedelta(days=5, hours=1)  # last knowable is day 4
    f = src.query("BTCUSDT", as_of)
    assert f.value == pytest.approx(1_000_000_000.0 + 4 * 10_000_000.0)
    assert f.scope == "BTCUSDT"
    assert f.available_at is not None and f.available_at <= as_of


def test_query_no_lookahead_before_any_data():
    src = _source("cg_market_cap", _chart_payload(days=10))
    f = src.query("BTCUSDT", _BASE)  # day 0 available_at = _BASE + 1d → nothing knowable
    assert f.value is None
    assert f.available_at is None


def test_query_unknown_symbol_returns_none():
    src = _source("cg_market_cap", _chart_payload(days=10))
    f = src.query("NOSUCHCOINXX", _BASE + timedelta(days=30))
    assert f.value is None
    assert f.available_at is None


# --------------------------------------------------------------------------- btc dominance


def test_parse_btc_dominance_snapshot_availability():
    fetch_at = _BASE + timedelta(days=3)
    pts = _parse_btc_dominance(_global_payload(52.5), fetch_at)
    assert len(pts) == 1
    assert pts[0].value == pytest.approx(52.5)
    # current snapshot: available_at == fetch time (we only knew it when we pulled it)
    assert pts[0].available_at == fetch_at


def test_parse_btc_dominance_missing():
    assert _parse_btc_dominance({"data": {}}, _BASE) == []
    assert _parse_btc_dominance({}, _BASE) == []
    assert _parse_btc_dominance(None, _BASE) == []


def test_btc_dominance_query_is_market_wide():
    src = _source("cg_btc_dominance", _global_payload(48.0))
    as_of = _BASE + timedelta(days=2)
    f = src.query("BTCUSDT", as_of)  # scope ignored → MARKET
    assert f.value == pytest.approx(48.0)
    assert f.scope == "MARKET"
    assert src.market_wide is True
    assert src.kind == "macro"


# --------------------------------------------------------------------------- robustness


def test_network_failure_returns_none_not_raises():
    def _bad(_url: str):
        raise RuntimeError("network down")
    src = CoinGeckoSource(metric="cg_market_cap", _fetcher=_bad)
    f = src.query("BTCUSDT", _BASE + timedelta(days=10))
    assert f.value is None


def test_unknown_metric_raises_at_construction():
    with pytest.raises(ValueError, match="unknown CoinGecko metric"):
        CoinGeckoSource(metric="not_a_metric")


# --------------------------------------------------------------------------- protocol + metadata


def test_datasource_protocol_attributes():
    for metric in COINGECKO_METRICS:
        src = CoinGeckoSource(metric=metric)
        assert src.name == metric
        assert src.metric == metric
        assert src.kind in ("price", "macro")
        assert src.prior
        assert src.transform_version == TRANSFORM_VERSION
        assert 0.0 < src.confidence <= 1.0


def test_low_confidence_flag():
    src = CoinGeckoSource(metric="cg_market_cap")
    assert src.confidence < 0.5
    assert src.low_confidence is True


def test_per_coin_metrics_are_price_kind():
    assert CoinGeckoSource(metric="cg_market_cap").kind == "price"
    assert CoinGeckoSource(metric="cg_total_volume").kind == "price"


def test_make_coingecko_sources_covers_all_metrics():
    srcs = make_coingecko_sources()
    assert {s.metric for s in srcs} == set(COINGECKO_METRICS)


def test_coin_id_map_has_btc():
    assert COIN_ID_MAP["BTCUSDT"] == "bitcoin"
