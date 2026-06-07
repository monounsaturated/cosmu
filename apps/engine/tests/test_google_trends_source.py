# intent: Offline, deterministic tests for GoogleTrendsSource — NO network, NO pytrends import.
# Every test injects a canned DataFrame-shaped stub so CI runs with zero keys and zero HTTP.
#
# Tests verify:
#   1. PIT contract: available_at is the FETCH time, NOT the week-bucket ts.
#   2. No fabrication: absent rows are absent (None), not zeroed-out.
#   3. Revision-safety surface: available_at > ts for all historical rows, which the store's
#      append-only contract surfaces correctly.
#   4. Low-confidence flag is set (0.2 < 0.5).
#   5. query() returns None when no snapshot is available before as_of.
#   6. query() returns the correct latest value when a snapshot is available.
#   7. Keyword aggregation: value is the mean across multiple keywords.
#   8. Empty/failed fetch returns [].

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from cosmu.data.sources.google_trends import GoogleTrendsSource, _TrendsPoint

# ---------------------------------------------------------------------------
# Offline fixture helpers
# ---------------------------------------------------------------------------

def _make_df(weeks_back: int = 4, keywords: tuple[str, ...] = ("bitcoin",), fetch_at: datetime | None = None) -> MagicMock:
    """Build a minimal pandas-DataFrame-shaped MagicMock with .empty, .iterrows(), .index.

    Each row has ts = Monday of a weekly bucket; value = 50 for all keywords.
    """
    import pandas as pd  # only for building the fixture in tests; NOT on the hot path

    base = datetime(2026, 1, 5, tzinfo=UTC)  # a Monday
    index = pd.DatetimeIndex([base + timedelta(weeks=i) for i in range(weeks_back)], tz="UTC")
    data = {kw: [50.0] * weeks_back for kw in keywords}
    df = pd.DataFrame(data, index=index)
    return df


def _make_empty_df() -> MagicMock:
    """Simulate an empty Trends response (rate-limit, no data)."""
    import pandas as pd
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_low_confidence_flag():
    """GoogleTrendsSource must always be low-confidence (<0.5) due to revision hazard."""
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_df())
    assert src.confidence == pytest.approx(0.2)
    assert src.low_confidence is True


def test_available_at_is_fetch_time_not_ts():
    """PIT contract: available_at must be the FETCH timestamp, strictly later than ts (week bucket).

    The core revision-safety check: we do NOT stamp available_at=ts (the week Monday) because the
    data was not knowable then — it was fetched now, and it may be rescaled on the next fetch.
    """
    before_call = datetime.now(tz=UTC)
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_df(weeks_back=3))
    pts = src.fetch_series(limit=100)
    after_call = datetime.now(tz=UTC)

    assert len(pts) == 3
    for pt in pts:
        # available_at must be within the fetch window (between before/after the call).
        assert before_call <= pt.available_at <= after_call, (
            f"available_at={pt.available_at} is not in the fetch window "
            f"[{before_call}, {after_call}]"
        )
        # ts is a historical Monday, strictly before the fetch.
        assert pt.ts < pt.available_at, (
            f"ts={pt.ts} must be BEFORE available_at={pt.available_at} — "
            "revision-safety: available_at is the fetch time, not the bucket time"
        )


def test_no_fabrication_empty_fetch_returns_empty_list():
    """A failed/empty fetch must return [] — absent data is absent, never fabricated as 0."""
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_empty_df())
    pts = src.fetch_series()
    assert pts == [], "Empty Trends response must produce [], not fabricated zeros"


def test_no_fabrication_exception_returns_empty_list():
    """A network/rate-limit exception must return [] — never crash, never fabricate."""
    def fail_fetcher(kw, tf):
        raise ConnectionError("Trends rate-limited")

    src = GoogleTrendsSource(_fetcher=fail_fetcher)
    pts = src.fetch_series()
    assert pts == [], "Exception during fetch must produce [], not crash"


def test_keyword_aggregation_mean():
    """Value must be the mean across all requested keywords for each week."""
    import pandas as pd

    base = datetime(2026, 1, 5, tzinfo=UTC)
    index = pd.DatetimeIndex([base], tz="UTC")
    # bitcoin=80, crypto=40 → mean=60
    df = pd.DataFrame({"bitcoin": [80.0], "crypto": [40.0]}, index=index)

    src = GoogleTrendsSource(keywords=("bitcoin", "crypto"), _fetcher=lambda kw, tf: df)
    pts = src.fetch_series(limit=10)

    assert len(pts) == 1
    assert pts[0].value == pytest.approx(60.0), "Value must be mean across keywords"


def test_query_returns_none_when_no_snapshot_before_as_of():
    """query() must return value=None when no fetched snapshot has available_at <= as_of.

    Simulates an empty fetch (no data available yet for a past as_of date).
    """
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_empty_df())
    past = datetime(2020, 1, 1, tzinfo=UTC)
    feat = src.query("MARKET", past)

    assert feat.value is None, "No snapshot before as_of must return value=None, not 0"
    assert feat.available_at is None


def test_query_returns_latest_value_before_as_of():
    """query() returns the most-recent fetched snapshot whose available_at <= as_of."""
    import pandas as pd

    base = datetime(2026, 1, 5, tzinfo=UTC)
    index = pd.DatetimeIndex([base, base + timedelta(weeks=1)], tz="UTC")
    df = pd.DataFrame({"bitcoin": [30.0, 70.0]}, index=index)

    src = GoogleTrendsSource(keywords=("bitcoin",), _fetcher=lambda kw, tf: df)

    # as_of = far future — both snapshots available → latest wins.
    far_future = datetime(2099, 1, 1, tzinfo=UTC)
    feat = src.query("MARKET", far_future)

    assert feat.value is not None
    assert feat.value == pytest.approx(70.0), "Latest available value must be returned"


def test_query_source_feature_shape():
    """SourceFeature returned by query() must have the correct structural attributes."""
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_df(weeks_back=2))
    as_of = datetime(2099, 1, 1, tzinfo=UTC)
    feat = src.query("MARKET", as_of)

    assert feat.name == "gtrends_search_interest"
    assert feat.scope == "MARKET"
    assert feat.as_of == as_of
    assert feat.confidence == pytest.approx(0.2)
    assert feat.low_confidence is True
    assert feat.transform_version == "gtrends-weekly-v1"
    assert feat.value is not None


def test_limit_respected():
    """fetch_series(limit=N) must return at most N most-recent points."""
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_df(weeks_back=10))
    pts = src.fetch_series(limit=3)
    assert len(pts) == 3, "limit must cap the number of returned points"
    # Verify they are the MOST RECENT (descending ts would be the oldest; ascending is the store order).
    # Sorted ascending by ts; last 3 of 10.
    expected_base = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(weeks=7)  # week index 7, 8, 9
    assert pts[0].ts.date() == expected_base.date()


def test_points_sorted_ascending_by_ts():
    """fetch_series() must return points sorted ascending by ts (oldest first)."""
    src = GoogleTrendsSource(_fetcher=lambda kw, tf: _make_df(weeks_back=5))
    pts = src.fetch_series(limit=100)
    tss = [p.ts for p in pts]
    assert tss == sorted(tss), "Points must be sorted ascending by ts"


def test_revision_risk_documented_in_prior():
    """The declared prior must mention the revision/rescaling hazard (doc contract)."""
    src = GoogleTrendsSource()
    assert "rescal" in src.prior.lower() or "revision" in src.prior.lower() or "review" in src.prior.lower(), (
        "prior must document the revision/rescaling hazard so the Gate sees it"
    )
