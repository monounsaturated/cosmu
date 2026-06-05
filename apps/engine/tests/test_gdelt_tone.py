"""GdeltToneProvider — offline tests with a canned TimelineTone fixture (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataStore, GdeltToneProvider, _points_from_gdelt_tone

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

FIXTURE = {
    "timeline": [
        {
            "data": [
                {"date": "20240101000000", "value": -2.5},
                {"date": "20240102000000", "value": 1.3},
                {"date": "20240103000000", "value": -0.8},
            ]
        }
    ]
}


def test_parse_tone_values_and_ascending_order():
    pts = _points_from_gdelt_tone(FIXTURE, limit=1000)
    assert len(pts) == 3
    assert pts[0].ts == _T0
    assert pts[0].value == -2.5
    assert pts[1].value == 1.3
    assert pts[2].value == -0.8
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)


def test_point_in_time_is_next_day():
    """A day's indexed articles are closed by end-of-day; available_at = ts + 1 day (no look-ahead)."""
    pts = _points_from_gdelt_tone(FIXTURE, limit=1000)
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)
        assert pt.available_at > pt.ts  # never look-ahead


def test_wrong_metric_returns_empty():
    p = GdeltToneProvider(_fetcher=lambda url: FIXTURE)
    assert p.fetch_series("MARKET", "not_gdelt_tone", limit=10) == []
    assert p.fetch_series("MARKET", "funding_rate", limit=10) == []


def test_respects_limit():
    pts = _points_from_gdelt_tone(FIXTURE, limit=2)
    assert len(pts) == 2
    # limit keeps the LAST N (most recent) points
    assert pts[-1].ts == _T0 + timedelta(days=2)


def test_empty_payload_returns_empty():
    assert _points_from_gdelt_tone({"timeline": []}, limit=100) == []
    assert _points_from_gdelt_tone({}, limit=100) == []


def test_fetch_failure_returns_empty():
    def bad_fetcher(url: str) -> dict:
        raise RuntimeError("network dead")

    p = GdeltToneProvider(_fetcher=bad_fetcher)
    # must not raise — one dead source never aborts the run
    assert p.fetch_series("MARKET", "gdelt_tone", limit=10) == []


def test_deduplicates_same_ts():
    dupe_fixture = {
        "timeline": [
            {
                "data": [
                    {"date": "20240101000000", "value": -2.5},
                    {"date": "20240101000000", "value": -1.0},  # same ts, later value wins
                ]
            }
        ]
    }
    pts = _points_from_gdelt_tone(dupe_fixture, limit=1000)
    assert len(pts) == 1
    assert pts[0].value == -1.0  # latest entry wins on dedup


def test_ingest_gdelt_tone_market_wide(tmp_path):
    from cosmu.ingest.pipeline import ingest_market_wide_numeric

    store = AltDataStore(tmp_path / "alt")
    p = GdeltToneProvider(_fetcher=lambda url: FIXTURE)
    count = ingest_market_wide_numeric(
        store, p, source_metric="gdelt_tone", stored_metric="gdelt_tone", provider_name="gdelt"
    )
    assert count == 3
    pts = store.read_all("gdelt", "MARKET", "gdelt_tone")
    assert len(pts) == 3
    # symbol-level read returns nothing (market-wide only)
    assert store.read_all("gdelt", "BTCUSDT", "gdelt_tone") == []
