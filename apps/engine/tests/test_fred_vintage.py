# FRED vintage / look-ahead fix (#3): the default series/observations returns the LATEST REVISED value for each
# date, and the old provider stamped it available `date + 1 day` — a back-test reading it then was using a number
# that did not exist yet (macro series are revised for months). The fix requests ALFRED `output_type=4` (initial
# release only) and stamps `available_at = realtime_start` (the first-published date). These tests pin that and
# FAIL on the old next-day-floor behaviour. All offline via an injected `_fetcher` (no live FRED key/network).

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.backtest import align_asof
from cosmu.data.market import Bar
from cosmu.data.providers.macro import FredMacroProvider

# ALFRED output_type=4 shape: one row per date = the value as FIRST published, with realtime_start = its
# first-publish date. The monthly print here is released ~6 weeks AFTER the period — a real macro release lag.
_CANNED = {
    "observations": [
        {"date": "2020-01-01", "realtime_start": "2020-02-15", "realtime_end": "9999-12-31", "value": "1.0"},
        {"date": "2020-02-01", "realtime_start": "2020-03-14", "realtime_end": "9999-12-31", "value": "2.0"},
        {"date": "2020-03-01", "realtime_start": "2020-04-15", "realtime_end": "9999-12-31", "value": "."},  # missing → skip
    ]
}


def _prov() -> FredMacroProvider:
    return FredMacroProvider(api_key="x", _fetcher=lambda url: _CANNED)


def test_available_at_is_first_release_not_next_day_floor():
    pts = _prov().fetch_series("MARKET", "GDP", limit=100)
    assert len(pts) == 2, "the missing-value row ('.') must be dropped"
    first = pts[0]
    assert first.ts == datetime(2020, 1, 1, tzinfo=UTC)
    # the honest first-known time is realtime_start (2020-02-15), NOT the old fabricated ts + 1 day (2020-01-02)
    assert first.available_at == datetime(2020, 2, 15, tzinfo=UTC)
    assert first.available_at != first.ts + timedelta(days=1), "old next-day floor would be look-ahead"
    assert first.value == 1.0


def test_requests_initial_release_only():
    captured: dict[str, str] = {}

    def cap(url: str) -> dict:
        captured["url"] = url
        return _CANNED

    FredMacroProvider(_fetcher=cap).fetch_series("MARKET", "GDP", limit=10)
    assert "output_type=4" in captured["url"], "must request ALFRED initial-release-only vintages"


def test_asof_join_hides_the_value_until_its_first_release():
    """A point-in-time bar join must NOT surface the macro value until realtime_start — the look-ahead the old
    next-day floor introduced. A bar the day after the period sees nothing; only a bar on/after the first
    release does."""
    pts = _prov().fetch_series("MARKET", "GDP", limit=100)
    one = Decimal("1")
    day_after_period = Bar(ts=datetime(2020, 1, 2, tzinfo=UTC), open=one, high=one, low=one, close=one, volume=one)
    after_release = Bar(ts=datetime(2020, 2, 20, tzinfo=UTC), open=one, high=one, low=one, close=one, volume=one)
    joined = align_asof(pts, [day_after_period, after_release])
    assert day_after_period.ts.isoformat() not in joined, "value not knowable the day after the period (no look-ahead)"
    assert joined[after_release.ts.isoformat()] == 1.0, "value becomes visible only on/after its first release"
