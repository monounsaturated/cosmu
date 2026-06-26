# Offline parse-step tests for the free alt-data providers (CBOE put/call, GDELT news). Canned payloads,
# no network: assert correct fields AND point-in-time `available_at` floors. (Coinglass liquidations were
# removed 2026-06-26 — the public history is now key-gated and the feature was direction-blind; graveyarded
# in config/feature_registry.py.)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import (
    _news_from_gdelt,
    _points_from_cboe_putcall,
)


def test_cboe_putcall_parses_and_floors_next_day():
    csv_text = "\n".join(
        [
            "CBOE Total Put/Call Ratio",  # preamble (no date → skipped)
            "DATE,PUT/CALL RATIO",        # header (no date → skipped)
            "01/03/2023,0.95",
            "01/04/2023,1.10",
        ]
    )
    pts = _points_from_cboe_putcall(csv_text, release_lag_days=1)
    assert len(pts) == 2
    assert pts[0].ts == datetime(2023, 1, 3, tzinfo=UTC)
    assert pts[0].value == 0.95
    # finalized after the close → available the next day (conservative point-in-time floor)
    assert pts[0].available_at == pts[0].ts + timedelta(days=1)
    assert pts[1].value == 1.10


def test_cboe_putcall_accepts_iso_dates_too():
    pts = _points_from_cboe_putcall("Date,Ratio\n2023-01-03,0.88\n", release_lag_days=1)
    assert len(pts) == 1
    assert pts[0].ts == datetime(2023, 1, 3, tzinfo=UTC)
    assert pts[0].value == 0.88


def test_gdelt_news_seendate_is_point_in_time_availability():
    payload = {
        "articles": [
            {"title": "Bitcoin surges as ETF inflows hit record", "seendate": "20230103T120000Z", "url": "http://x"},
            {"title": "Exchange hack triggers a broad selloff", "seendate": "20230102T080000Z", "url": "http://y"},
            {"title": "", "seendate": "20230101T000000Z"},  # empty title → dropped
        ]
    }
    items = _news_from_gdelt(payload)
    assert len(items) == 2  # the empty-title row is dropped
    # sorted ascending by ts; seendate IS the availability time (we knew it when GDELT indexed it)
    assert items[0].ts == datetime(2023, 1, 2, 8, 0, 0, tzinfo=UTC)
    assert items[0].available_at == items[0].ts
    assert items[0].headline == "Exchange hack triggers a broad selloff"
    assert items[1].headline.startswith("Bitcoin surges")
