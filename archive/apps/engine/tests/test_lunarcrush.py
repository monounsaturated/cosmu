"""LunarCrushProvider — offline tests with a canned v4 time-series fixture (no network). Key-gated."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataStore, LunarCrushProvider

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

# LunarCrush v4 coin time-series rows: `time` (unix s) + native fields. social_sentiment maps to "sentiment".
FIXTURE = {
    "data": [
        {"time": int((_T0 + timedelta(days=i)).timestamp()), "social_volume": 1000 + i * 100, "sentiment": 60 + i, "galaxy_score": 70 + i}
        for i in range(4)
    ]
}


def _provider(api_key: str = "test-key") -> LunarCrushProvider:
    return LunarCrushProvider(api_key=api_key, _fetcher=lambda url: FIXTURE)


def test_no_key_degrades_honestly_to_empty() -> None:
    """Without a key the provider returns [] — honest degradation, never a fabricated social read."""
    p = LunarCrushProvider(api_key="", _fetcher=lambda url: FIXTURE)
    assert p.fetch_series("BTCUSDT", "social_volume", limit=10) == []


def test_maps_semantic_metric_to_native_field() -> None:
    p = _provider()
    sent = p.fetch_series("BTCUSDT", "social_sentiment", limit=10)  # → native "sentiment"
    assert [pt.value for pt in sent] == [60.0, 61.0, 62.0, 63.0]
    vol = p.fetch_series("BTCUSDT", "social_volume", limit=10)
    assert [pt.value for pt in vol] == [1000.0, 1100.0, 1200.0, 1300.0]
    galaxy = p.fetch_series("BTCUSDT", "galaxy_score", limit=10)
    assert [pt.value for pt in galaxy] == [70.0, 71.0, 72.0, 73.0]


def test_point_in_time_is_next_day() -> None:
    """A day's social bucket is known only after the day closes → available_at == ts + 1 day (no look-ahead)."""
    p = _provider()
    for pt in p.fetch_series("BTCUSDT", "social_volume", limit=10):
        assert pt.available_at == pt.ts + timedelta(days=1)


def test_unknown_metric_returns_empty() -> None:
    p = _provider()
    assert p.fetch_series("BTCUSDT", "not_a_social_metric", limit=10) == []


def test_respects_limit() -> None:
    p = _provider()
    assert len(p.fetch_series("BTCUSDT", "social_volume", limit=2)) == 2


def test_ingest_lunarcrush_per_symbol(tmp_path) -> None:
    from cosmu.ingest.pipeline import ingest_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider()
    count = ingest_numeric(store, p, ["BTCUSDT", "ETHUSDT"], "social_sentiment", provider_name="lunarcrush")
    assert count == 8  # 4 points x 2 symbols
    assert len(store.read_all("lunarcrush", "BTCUSDT", "social_sentiment")) == 4
