"""Reddit daily post + comment VOLUME provider — offline tests (no network, no credentials).

Point-in-time invariants tested:
- available_at = midnight UTC of the DAY AFTER the observation date (day-after PIT; no look-ahead)
- Gaps are absent (empty list), never fabricated as 0
- No credentials → honest empty (not a crash, not a fabricated value)
- Wrong metric → empty
- DataSource.query respects as_of (never returns a point whose available_at > as_of)
- low_confidence is set correctly on both DataSource adapters
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from cosmu.data.providers._types import AltDataPoint
from cosmu.data.sources.reddit_volume import (
    DEFAULT_SUBREDDITS,
    TRANSFORM_VERSION,
    RedditCommentVolumeDataSource,
    RedditVolumeDataSource,
    RedditVolumeProvider,
    _count_posts_for_day,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _listing(posts: list[dict]) -> dict:
    """Shape a Reddit /search.json listing payload from a list of post dicts."""
    return {
        "kind": "Listing",
        "data": {
            "dist": len(posts),
            "children": [{"kind": "t3", "data": p} for p in posts],
        },
    }


def _post(*, name: str, created_utc: int, num_comments: int = 5) -> dict:
    return {"name": name, "created_utc": created_utc, "num_comments": num_comments}


# A fixed reference day that is safely in the past.
_REF_DAY = date(2024, 3, 15)
_REF_MIDNIGHT = int(datetime(2024, 3, 15, tzinfo=UTC).timestamp())

_NO_SLEEP = lambda _: None  # noqa: E731 — injected to skip time.sleep in tests


def _posts_in_day(n: int = 3, comments_each: int = 10) -> list[dict]:
    """n posts with created_utc inside _REF_DAY."""
    return [_post(name=f"t3_{i:06d}", created_utc=_REF_MIDNIGHT + i * 3600, num_comments=comments_each) for i in range(n)]


def _provider_with_fetcher(fetcher, *, token_fn=None, subreddits=("testcrypto",)) -> RedditVolumeProvider:
    return RedditVolumeProvider(
        subreddits=subreddits,
        _fetcher=fetcher,
        _token_fn=token_fn or (lambda cid, secret: "mock-token"),
        _sleep_fn=_NO_SLEEP,
    )


# ── _count_posts_for_day ─────────────────────────────────────────────────────

def test_count_posts_for_day_basic():
    """Posts inside the day window are counted; posts outside are skipped."""
    posts_in = _posts_in_day(n=4, comments_each=7)
    # One post outside the day (previous day)
    post_out = _post(name="t3_outside", created_utc=_REF_MIDNIGHT - 3600, num_comments=99)

    call_n = [0]

    def fetcher(url: str, token: str) -> dict:
        assert token == "tok"
        call_n[0] += 1
        if call_n[0] == 1:
            return _listing(posts_in + [post_out])
        return _listing([])

    p, c = _count_posts_for_day("testcrypto", _REF_DAY, "tok", fetcher=fetcher)
    assert p == 4
    assert c == 4 * 7


def test_count_posts_for_day_network_error_returns_zero_tuple():
    """A failing fetch for a subreddit returns (0, 0) — never raises."""
    def bad_fetcher(url: str, token: str) -> dict:
        raise RuntimeError("network down")

    p, c = _count_posts_for_day("testcrypto", _REF_DAY, "tok", fetcher=bad_fetcher)
    assert p == 0 and c == 0


def test_count_posts_for_day_empty_listing():
    def fetcher(url: str, token: str) -> dict:
        return _listing([])

    p, c = _count_posts_for_day("testcrypto", _REF_DAY, "tok", fetcher=fetcher)
    assert p == 0 and c == 0


def test_count_posts_deduplicates_by_name():
    """The same post name appearing twice is counted once (pagination overlap guard)."""
    dup = _post(name="t3_dup", created_utc=_REF_MIDNIGHT + 1800, num_comments=3)

    calls = [0]

    def fetcher(url: str, token: str) -> dict:
        calls[0] += 1
        if calls[0] == 1:
            return _listing([dup, dup])  # duplicate in first page
        return _listing([])

    p, c = _count_posts_for_day("testcrypto", _REF_DAY, "tok", fetcher=fetcher)
    assert p == 1 and c == 3


# ── RedditVolumeProvider ─────────────────────────────────────────────────────

def test_provider_no_credentials_returns_empty():
    """Without REDDIT_CLIENT_ID/SECRET the provider must return [] — honest, no crash."""
    p = RedditVolumeProvider(subreddits=("testcrypto",), _sleep_fn=_NO_SLEEP)
    env_clean = {k: v for k, v in os.environ.items() if k not in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")}
    with patch.dict(os.environ, env_clean, clear=True):
        result = p.fetch_series("MARKET", "reddit_post_volume", limit=5)
    assert result == []


def test_provider_wrong_metric_returns_empty():
    """Unknown metric → [] (never a crash)."""
    p = _provider_with_fetcher(lambda url, tok: _listing([]))
    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec"}):
        assert p.fetch_series("MARKET", "reddit_sentiment", limit=1) == []


def test_provider_pit_available_at_is_day_after():
    """available_at MUST equal midnight UTC of the day AFTER ts (the observation date)."""
    # Build a provider that returns posts for whatever day it queries.
    call_count = [0]

    def fetcher(url: str, token: str) -> dict:
        call_count[0] += 1
        if call_count[0] % 2 == 1:
            # We don't know which day the provider will query; craft posts for it
            # The provider fetches yesterday, so we return generic posts in-window.
            # The key check is the available_at stamp, not the exact day.
            return _listing([_post(name=f"t3_p{call_count[0]}", created_utc=1_700_000_000, num_comments=5)])
        return _listing([])

    # We use limit=1 so the provider queries exactly one day (yesterday UTC).
    p = _provider_with_fetcher(fetcher)
    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec"}):
        series = p.fetch_series("MARKET", "reddit_post_volume", limit=1)

    # May be empty if the post's created_utc falls outside yesterday's window — that is fine
    # for the PIT invariant test. But if it returned points, verify the stamp.
    # More deterministic: build a provider that returns posts exactly in yesterday's window.
    yesterday = datetime.now(tz=UTC).date() - timedelta(days=1)
    yday_midnight = int(datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=UTC).timestamp())
    posts_yesterday = [_post(name="t3_yd0", created_utc=yday_midnight + 3600, num_comments=2)]

    call_count2 = [0]

    def fetcher2(url: str, token: str) -> dict:
        call_count2[0] += 1
        if call_count2[0] % 2 == 1:
            return _listing(posts_yesterday)
        return _listing([])

    p2 = _provider_with_fetcher(fetcher2)
    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec"}):
        series2 = p2.fetch_series("MARKET", "reddit_post_volume", limit=1)

    assert len(series2) == 1
    pt = series2[0]
    assert pt.ts.date() == yesterday
    # THE PIT INVARIANT: available_at is exactly one day after ts
    assert pt.available_at == pt.ts + timedelta(days=1)
    # Sanity: ts < available_at (data is never known at observation time)
    assert pt.ts < pt.available_at


def test_provider_no_fabricated_zero_on_token_failure():
    """If token acquisition fails, return [] — never a fabricated 0 value."""
    def bad_token(cid: str, secret: str) -> str:
        raise RuntimeError("auth failed")

    p = RedditVolumeProvider(
        subreddits=("testcrypto",),
        _fetcher=lambda url, tok: _listing([]),
        _token_fn=bad_token,
        _sleep_fn=_NO_SLEEP,
    )
    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec"}):
        result = p.fetch_series("MARKET", "reddit_post_volume", limit=3)
    assert result == []


def test_provider_post_and_comment_metrics_are_separate():
    """post_volume and comment_volume produce different numeric values from the same raw data."""
    yesterday = datetime.now(tz=UTC).date() - timedelta(days=1)
    yday_midnight = int(datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=UTC).timestamp())
    posts_yesterday = [_post(name=f"t3_{i}", created_utc=yday_midnight + i * 1800, num_comments=20) for i in range(3)]

    call_count = [0]

    def fetcher(url: str, token: str) -> dict:
        call_count[0] += 1
        if call_count[0] % 2 == 1:
            return _listing(posts_yesterday)
        return _listing([])

    p = _provider_with_fetcher(fetcher)
    with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec"}):
        call_count[0] = 0
        pv = p.fetch_series("MARKET", "reddit_post_volume", limit=1)
        call_count[0] = 0
        cv = p.fetch_series("MARKET", "reddit_comment_volume", limit=1)

    assert len(pv) == 1 and len(cv) == 1
    assert pv[0].value == 3.0      # 3 posts
    assert cv[0].value == 60.0     # 3 posts * 20 comments


# ── DataSource adapters (registry protocol) ──────────────────────────────────

def _make_ds_with_fixtures(
    points: list[AltDataPoint],
    *,
    metric: str = "reddit_post_volume",
) -> RedditVolumeDataSource | RedditCommentVolumeDataSource:
    """Build a DataSource whose provider returns fixed pre-built AltDataPoints (no network)."""

    class _FixedProvider:
        """Bypasses all the OAuth/HTTP plumbing and returns canned points."""
        def fetch_series(self, symbol: str, metric_: str, *, limit: int) -> list[AltDataPoint]:
            if metric_ != metric:
                return []
            return points

    if metric == "reddit_post_volume":
        ds = RedditVolumeDataSource()
    else:
        ds = RedditCommentVolumeDataSource()
    # Inject the canned provider directly.
    object.__setattr__(ds, "_provider", _FixedProvider())
    return ds


def test_datasource_query_respects_asof_pit():
    """DataSource.query must return None when as_of < available_at (no look-ahead)."""
    obs_day = date(2024, 4, 10)
    ts = datetime(obs_day.year, obs_day.month, obs_day.day, tzinfo=UTC)
    available_at = ts + timedelta(days=1)  # midnight the day after

    pt = AltDataPoint(ts=ts, available_at=available_at, value=5.0)
    ds = _make_ds_with_fixtures([pt], metric="reddit_post_volume")

    # Query AT the ts timestamp — data is NOT yet knowable (available_at is next day).
    feat_early = ds.query("MARKET", ts)
    assert feat_early.value is None, "must not return data before available_at"

    # Query at exactly available_at — NOW it is knowable.
    feat_exact = ds.query("MARKET", available_at)
    assert feat_exact.value == 5.0, "must return data at available_at"
    assert feat_exact.available_at == available_at

    # Query 1 hour after available_at — still knowable.
    feat_after = ds.query("MARKET", available_at + timedelta(hours=1))
    assert feat_after.value == 5.0


def test_datasource_query_multiple_points_returns_latest_knowable():
    """When multiple points exist, query returns the LATEST whose available_at <= as_of."""
    days = [date(2024, 4, d) for d in (10, 11, 12)]
    points = []
    for d in days:
        ts = datetime(d.year, d.month, d.day, tzinfo=UTC)
        points.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=float(d.day)))

    ds = _make_ds_with_fixtures(points, metric="reddit_post_volume")

    # as_of = midnight Apr 12 + 1 day = Apr 13 midnight — only Apr 10 and Apr 11 are knowable
    # (Apr 11's available_at = Apr 12 midnight; Apr 12's available_at = Apr 13 midnight)
    apr_13 = datetime(2024, 4, 13, tzinfo=UTC)
    feat = ds.query("MARKET", apr_13 - timedelta(hours=1))  # 23:00 Apr 12 UTC
    # Apr 12's available_at = Apr 13 midnight > 23:00 Apr 12 → not knowable
    # Apr 11's available_at = Apr 12 midnight <= 23:00 Apr 12 → knowable (value=11)
    assert feat.value == 11.0


def test_datasource_low_confidence_flag():
    """Both DataSource adapters must declare low_confidence = True."""
    ds_posts = RedditVolumeDataSource()
    ds_comments = RedditCommentVolumeDataSource()
    assert ds_posts.low_confidence is True
    assert ds_comments.low_confidence is True
    assert ds_posts.confidence < 0.5
    assert ds_comments.confidence < 0.5


def test_datasource_transform_version_pinned():
    """transform_version must match the module constant so survivors are re-runnable."""
    assert RedditVolumeDataSource().transform_version == TRANSFORM_VERSION
    assert RedditCommentVolumeDataSource().transform_version == TRANSFORM_VERSION


def test_datasource_query_returns_none_when_no_data():
    """Empty provider → DataSource.query returns SourceFeature with value=None (not a crash)."""
    ds = _make_ds_with_fixtures([], metric="reddit_post_volume")
    feat = ds.query("MARKET", datetime(2024, 6, 1, tzinfo=UTC))
    assert feat.value is None
    assert feat.available_at is None


def test_datasource_kind_and_metric_names():
    """Check declared names match the store keys the orchestrator will wire."""
    ds_posts = RedditVolumeDataSource()
    ds_comments = RedditCommentVolumeDataSource()
    assert ds_posts.name == "reddit_post_volume"
    assert ds_posts.kind == "social"
    assert ds_posts.metric == "reddit_post_volume"
    assert ds_comments.name == "reddit_comment_volume"
    assert ds_comments.kind == "social"
    assert ds_comments.metric == "reddit_comment_volume"


def test_default_subreddits_are_expected():
    """Verify the default subreddit list includes the finance/crypto subs in the spec."""
    assert "cryptocurrency" in DEFAULT_SUBREDDITS
    assert "bitcoin" in DEFAULT_SUBREDDITS
    assert "wallstreetbets" in DEFAULT_SUBREDDITS


def test_datasource_comment_volume_source_returns_correct_values():
    """RedditCommentVolumeDataSource returns comment count, not post count."""
    obs_day = date(2024, 5, 1)
    ts = datetime(obs_day.year, obs_day.month, obs_day.day, tzinfo=UTC)
    pt = AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=150.0)  # 150 comments

    ds = _make_ds_with_fixtures([pt], metric="reddit_comment_volume")
    feat = ds.query("MARKET", ts + timedelta(days=2))
    assert feat.value == 150.0
    assert feat.name == "reddit_comment_volume"
